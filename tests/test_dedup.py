"""Smoke test for stable-key release deduplication.

Verifies:
- release_key returns identical keys for two parses of the same Reuters
  event even when the original titles differ slightly.
- dedup_releases keeps the first occurrence and drops the rest.
- catalogue grouping after dedup never lets the latest occurrence appear
  in the previous-occurrences slice.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.normalize import dedup_releases, normalize_release_name, release_key
from core.parsers import Block, Release, extract_releases

PASS = 0
FAIL = 0


def expect(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok - {label}")
    else:
        FAIL += 1
        print(f"  FAIL - {label}  {detail}")


# Two slightly different titles for the same Reuters event on the same day
r_a = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD", kind="frozen_week",
    title="United States - Retail Sales MM (Mar)", importance="****",
    date_str="2026-04-21", countries=["US"], themes=["Growth"], raw_block="block A",
)
r_b = Release(
    source_file="WEEKPM.txt", block_stem="WEEKPM", region="", kind="pm_style",
    title="United States - Retail Sales / Ex-Autos (Mar)", importance="****",
    date_str="2026-04-21", countries=["US"], themes=["Growth"], raw_block="block B",
)
r_prev = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD", kind="frozen_week",
    title="United States - Retail Sales MM (Feb)", importance="****",
    date_str="2026-03-17", countries=["US"], themes=["Growth"], raw_block="block prev",
)

expect("release_key matches across files for same event",
       release_key(r_a) == release_key(r_b), f"{release_key(r_a)} vs {release_key(r_b)}")
expect("release_key differs for different dates",
       release_key(r_a) != release_key(r_prev))

# Dedup keeps the first occurrence
dedup = dedup_releases([r_a, r_b, r_prev])
expect("dedup len 2", len(dedup) == 2, f"got {len(dedup)}")
expect("first occurrence kept", dedup[0] is r_a)
expect("previous (different date) kept", dedup[1] is r_prev)

# Empty / None safety
expect("empty list dedup", dedup_releases([]) == [])
expect("None dedup", dedup_releases(None) == [])
expect("None release key empty", release_key(None) == "")

# End-to-end: catalogue-style grouping after dedup never repeats latest in previous
all_for_country = [r_a, r_b, r_prev]
deduped = dedup_releases(all_for_country)
groups = {}
for r in deduped:
    name, _, _ = normalize_release_name(r.title)
    groups.setdefault(name, []).append(r)
import datetime as _dt
from utils.text import parse_release_date
for name, rs in groups.items():
    rs_sorted = sorted(rs, key=lambda r: parse_release_date(r.date_str) or _dt.date.min, reverse=True)
    latest = rs_sorted[0]
    previous = rs_sorted[1:]
    latest_dates = {r.date_str for r in [latest]}
    previous_dates = {r.date_str for r in previous}
    expect(f"[{name}] latest date not in previous",
           latest.date_str not in previous_dates,
           f"latest={latest.date_str} previous_dates={previous_dates}")

# Day headers must not produce releases (regression guard from the
# weekly fix - a day-header-only block should yield zero releases)
b_only_days = Block(
    stem="USD_WEEK", source_file="USD_WEEK.txt",
    raw_text="MONDAY 13 APR 2026\n\nTUESDAY 14 APR 2026 - RELEASED\n",
)
expect("day-header-only block emits zero releases",
       len(extract_releases(b_only_days)) == 0)

print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
