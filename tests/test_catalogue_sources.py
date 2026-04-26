"""Regression tests for Country Release Catalogue source scoping.

Locks in the fixes for two bugs:
  1. Country = US was pulling rows from EUR_WEEK.txt / SHORT_WEEK.txt etc.
     Now: catalogue is restricted to USD_WEEK.txt (+ optional live).
  2. Narrative commentary lines (e.g. "For the regional story this matters...")
     were being parsed as release titles. Now: rejected by
     _looks_like_commentary_fragment.
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.config import (
    COUNTRY_SOURCE_PRIORITY,
    country_source_status,
    sources_for_country,
)
from core.parsers import (
    Block,
    _looks_like_commentary_fragment,
    _looks_like_title_line,
    extract_releases,
)
from core.normalize import dedup_releases

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


# ============================================================
# 1. sources_for_country - country -> file allow-list
# ============================================================

us_frozen = sources_for_country("US")
expect("US frozen = [USD_WEEK.txt]", us_frozen == ["USD_WEEK.txt"], f"got {us_frozen}")

us_live = sources_for_country("US", include_live=True)
expect("US +live = [USD_WEEK.txt, USD_WEEK_LIVE_MACRO.txt]",
       us_live == ["USD_WEEK.txt", "USD_WEEK_LIVE_MACRO.txt"], f"got {us_live}")

# UK pulls from country file FIRST, then DM bucket as fallback.
uk_frozen = sources_for_country("UK")
expect("UK frozen has GBP_WEEK.txt before DM_WEEK.txt",
       uk_frozen == ["GBP_WEEK.txt", "DM_WEEK.txt"], f"got {uk_frozen}")

# Australia: AUD first, DM fallback.
au_frozen = sources_for_country("Australia")
expect("Australia frozen = [AUD_WEEK.txt, DM_WEEK.txt]",
       au_frozen == ["AUD_WEEK.txt", "DM_WEEK.txt"], f"got {au_frozen}")

# Eurozone: EUR file only (no per-country file exists).
de_frozen = sources_for_country("Germany")
expect("Germany frozen = [EUR_WEEK.txt]", de_frozen == ["EUR_WEEK.txt"], f"got {de_frozen}")

# China: CNH first, EM fallback.
cn_frozen = sources_for_country("China")
expect("China frozen = [CNH_WEEK.txt, EM_WEEK.txt]",
       cn_frozen == ["CNH_WEEK.txt", "EM_WEEK.txt"], f"got {cn_frozen}")

# Live file always appended after frozen entries.
cn_live = sources_for_country("China", include_live=True)
expect("China +live ends with EM_WEEK_LIVE_MACRO.txt",
       cn_live[-1] == "EM_WEEK_LIVE_MACRO.txt", f"got {cn_live}")

# Unknown country returns empty list.
expect("Unknown country -> []", sources_for_country("Atlantis") == [])

# US catalogue NEVER includes EUR / SHORT / DM files.
us_all = set(sources_for_country("US", include_live=True))
forbidden = {"EUR_WEEK.txt", "SHORT_WEEK.txt", "DM_WEEK.txt", "EM_WEEK.txt",
             "EUR_WEEK_LIVE_MACRO.txt", "DM_WEEK_LIVE_MACRO.txt", "EM_WEEK_LIVE_MACRO.txt"}
expect("US catalogue never includes EUR/SHORT/DM/EM files",
       not (us_all & forbidden), f"intersection={us_all & forbidden}")


# ============================================================
# 2. country_source_status - frozen vs live classification
# ============================================================

expect("USD_WEEK.txt -> frozen",
       country_source_status("USD_WEEK.txt") == "frozen")
expect("USD_WEEK_LIVE_MACRO.txt -> live",
       country_source_status("USD_WEEK_LIVE_MACRO.txt") == "live")
expect("DM_WEEK_LIVE_MACRO.txt -> live",
       country_source_status("DM_WEEK_LIVE_MACRO.txt") == "live")
expect("WEEKPM.txt -> other",
       country_source_status("WEEKPM.txt") == "other")
expect("'' -> other",
       country_source_status("") == "other")


# ============================================================
# 3. Commentary-fragment rejection
# ============================================================

reject_titles = [
    "For the regional story this matters because France is too large to absorb simultaneous soft consensus prints.",
    "False dawn / rebound from collapse / miss vs consensus / domestic weakness / foreign-led only impulse next print.",
    "This matters because the bigger picture is starting to shift toward dovish expectations.",
    "What this means for markets going forward is that the central bank will likely cut earlier.",
    "Bottom line: growth has stalled and the next print confirms the soft trajectory ahead.",
]
for t in reject_titles:
    expect(f"reject commentary: {t[:60]}...",
           _looks_like_commentary_fragment(t) and not _looks_like_title_line(t))

keep_titles = [
    "United States - Retail Sales (Mar)",
    "US - CPI / Core CPI",
    "Australia - Labour Force (Mar)",
    "Euro Zone - HICP Final YY",
    "RBA Decision (Apr)",
    "Cleveland Fed Median CPI",
    "NFP March",
]
for t in keep_titles:
    expect(f"keep title: {t}",
           not _looks_like_commentary_fragment(t) and _looks_like_title_line(t))


# ============================================================
# 4. End-to-end: a synthetic block with both real release fields
#    AND commentary should produce only the real release.
# ============================================================

mock_text = """\
United States - Retail Sales (Mar) ****
Release Date: 17 Apr 2026
Importance: ****
Reuters Data: 0.6% MoM (consensus 0.4%)
Actual: 0.6%
Prior: 0.2%

Economist Layer

For the regional story this matters because consumer spending in the second half remains the swing factor for nominal GDP.
False dawn / rebound from collapse / miss vs consensus / domestic weakness / foreign-led only.

What this means for markets is that the dollar holds the bid and curves steepen.
"""

block = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=mock_text)
rels = extract_releases(block)
expect("synthetic block yields exactly 1 release", len(rels) == 1, f"got {len(rels)}")
if rels:
    r = rels[0]
    expect("title is the real release header",
           "Retail Sales" in r.title and "regional story" not in r.title.lower(),
           f"title={r.title!r}")
    expect("title is not a commentary fragment",
           not _looks_like_commentary_fragment(r.title),
           f"title={r.title!r}")


# ============================================================
# 5. Country priority map sanity
# ============================================================

# Every priority map entry must reference real WEEK files (str ending with
# .txt, no empty strings).
all_priority_files = []
for c, spec in COUNTRY_SOURCE_PRIORITY.items():
    for f in (spec.get("frozen") or []) + (spec.get("live") or []):
        all_priority_files.append((c, f))
        expect(f"{c} priority entry '{f}' is non-empty",
               isinstance(f, str) and f.endswith(".txt") and len(f) > 4,
               f"got {f!r}")

# All EM countries must have EM_WEEK.txt as their last frozen fallback or
# only frozen entry.
em_countries = ["China", "Korea", "India", "Brazil", "Mexico", "Turkey",
                "Poland", "Taiwan", "South Africa"]
for c in em_countries:
    fr = sources_for_country(c)
    expect(f"{c} EM bucket present", "EM_WEEK.txt" in fr, f"got {fr}")

# All DM countries (with DM bucket fallback) must have DM_WEEK.txt.
dm_countries = ["UK", "Japan", "Canada", "Australia", "Switzerland",
                "Norway", "Sweden", "New Zealand"]
for c in dm_countries:
    fr = sources_for_country(c)
    expect(f"{c} DM bucket present", "DM_WEEK.txt" in fr, f"got {fr}")


# ============================================================
# 6. dedup_releases prefers FIRST occurrence (so frozen wins over live
#    when allowed_files lists frozen first)
# ============================================================

from core.parsers import Release

frozen_r = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD", kind="frozen_week",
    title="United States - CPI (Mar)", importance="****",
    date_str="2026-04-15", countries=["US"], themes=["Inflation"], raw_block="frozen text",
)
live_r = Release(
    source_file="USD_WEEK_LIVE_MACRO.txt", block_stem="USD_WEEK_LIVE_MACRO",
    region="USD", kind="live_week",
    title="US - CPI Mar", importance="****",
    date_str="2026-04-15", countries=["US"], themes=["Inflation"], raw_block="live text",
)
# frozen listed first
out = dedup_releases([frozen_r, live_r])
expect("frozen wins over live duplicate (frozen-first order)",
       len(out) == 1 and out[0].source_file == "USD_WEEK.txt",
       f"got {[r.source_file for r in out]}")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
