"""Smoke test for Weekly Monitor parser fixes:
- day headers (MONDAY 13 APR 2026) are not emitted as releases
- DATA WINDOW lines are captured on Block
- a multi-week block is split into one Block per data window
- block_data_window() infers from release dates when no explicit window
"""
import sys, datetime as _dt
import os as _os
_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.parsers import (
    Block,
    block_data_window,
    extract_blocks,
    extract_releases,
    find_data_windows,
    split_block_by_data_window,
)

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

USD_TWO_WEEKS = """\
USD Frozen Week

Data window: 13 Apr 2026 to 17 Apr 2026

MONDAY 13 APR 2026

United States - CPI (Mar) ****

Release Date: 2026-04-15
Importance: 4

Reuters Data: Headline CPI 2.6% YoY.

TUESDAY 14 APR 2026 - RELEASED

United States - Retail Sales MM (Mar) ***

Release Date: 2026-04-16
Importance: 3

Actual: 0.4%   Prior: 0.2%   Poll: 0.3%

WEDNESDAY 15 APR 2026

United States - Industrial Production (Mar) **

Release Date: 2026-04-17
Importance: 2

Data window: 20 Apr 2026 to 24 Apr 2026

MONDAY 20 APR 2026

United States - Existing Home Sales (Mar) ***

Release Date: 2026-04-22
Importance: 3

Reuters Data: 4.05M annualized.

FRIDAY 24 APR 2026

United States - U Mich Sentiment Final (Apr) **

Release Date: 2026-04-25
Importance: 2
"""

# 1. find_data_windows finds both
windows = find_data_windows(USD_TWO_WEEKS)
expect("two data windows found", len(windows) == 2, f"got {len(windows)}")
expect("first window is 13->17 Apr", windows[0][0] == "13 Apr 2026 to 17 Apr 2026", repr(windows[0][0]))
expect("second window is 20->24 Apr", windows[1][0] == "20 Apr 2026 to 24 Apr 2026", repr(windows[1][0]))

# 2. extract_blocks splits a USD_WEEK marker-less file by data window
blocks = extract_blocks(USD_TWO_WEEKS, source_file="USD_WEEK.txt")
weekly_blocks = [b for b in blocks if b.data_window]
expect("two weekly sub-blocks emitted", len(weekly_blocks) == 2, f"got {[b.data_window for b in blocks]}")

# 3. Each sub-block has the right window assigned
expect("sub-block 0 window", weekly_blocks[0].data_window == "13 Apr 2026 to 17 Apr 2026")
expect("sub-block 1 window", weekly_blocks[1].data_window == "20 Apr 2026 to 24 Apr 2026")

# 4. Releases extracted from week 1 do NOT contain a "MONDAY 13 APR" item
rels_w1 = extract_releases(weekly_blocks[0])
titles_w1 = [r.title for r in rels_w1]
print("    week-1 release titles:", titles_w1)
expect("week 1 has 3 real releases", len(rels_w1) == 3, f"got {len(rels_w1)}")
expect("no day-header release in week 1",
       not any("MONDAY" in (t or "").upper() or "TUESDAY" in (t or "").upper() or "WEDNESDAY" in (t or "").upper()
               for t in titles_w1),
       repr(titles_w1))

rels_w2 = extract_releases(weekly_blocks[1])
titles_w2 = [r.title for r in rels_w2]
print("    week-2 release titles:", titles_w2)
expect("week 2 has 2 real releases", len(rels_w2) == 2, f"got {len(rels_w2)}")
expect("no day-header release in week 2",
       not any(t and t.upper().startswith(("MONDAY", "FRIDAY")) for t in titles_w2),
       repr(titles_w2))

# 5. block_data_window infers from dates when explicit window is absent
NO_WINDOW = """\
United States - CPI (Mar) ****

Release Date: 2026-04-15
Importance: 4

United States - Retail Sales MM (Mar) ***

Release Date: 2026-04-17
Importance: 3
"""
b_nowin = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=NO_WINDOW)
label, s, e = block_data_window(b_nowin)
expect("inferred window non-empty", bool(label), repr(label))
expect("inferred start 2026-04-15", s == _dt.date(2026, 4, 15), repr(s))
expect("inferred end 2026-04-17", e == _dt.date(2026, 4, 17), repr(e))

# 6. A pure day header in isolation must not generate a release
ONLY_DAY = "MONDAY 13 APR 2026\n\nTUESDAY 14 APR 2026 - RELEASED\n"
b_only = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=ONLY_DAY)
expect("day-header-only block emits zero releases", len(extract_releases(b_only)) == 0)

# 7. split_block_by_data_window is a no-op without markers
b_plain = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=NO_WINDOW)
parts = split_block_by_data_window(b_plain)
expect("no markers => single block", len(parts) == 1 and parts[0].data_window is None)

# 8. streamlit_app imports cleanly
import streamlit_app  # noqa: F401
expect("streamlit_app imports", True)

print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
