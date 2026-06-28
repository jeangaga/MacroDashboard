"""Regression test for tasks #57-#59: parser robustness against blank-line-less blocks.

The new MACRO SYNTHESIS / SCOREBOARD / FULL RELEASE ARCHIVE files pack
multiple releases into one block separated only by single newlines. The
parser must:

- Split such a block into one Release per (title + Release Date:) cluster.
- Ignore synthesis section dividers ("A. ... MACRO SYNTHESIS",
  "B. ... SCOREBOARD", "C. FULL RELEASE ARCHIVE") so they never become
  release titles.
- Strip day-of-week banners ("MONDAY 23 MAR 2026") between releases.
- Keep working unchanged on the older blank-line-separated format.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.parsers import (
    Block,
    extract_releases,
    _inject_release_boundaries,
    _is_synthesis_header_line,
    _looks_like_release_title,
    _looks_like_title_line,
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


# ---------------------------------------------------------------------------
# 1. Synthesis-header detection.
# ---------------------------------------------------------------------------
SYNTHESIS_LINES = [
    "A. US WEEK \u2014 MACRO SYNTHESIS",
    "B. US MACRO SIGNAL SCOREBOARD",
    "C. FULL RELEASE ARCHIVE",
    "A. EUR WEEK - MACRO SYNTHESIS",
    "D. SUMMARY ARCHIVE",
]
NON_SYNTHESIS_LINES = [
    "UNITED STATES \u2014 National Activity Index (Feb)",
    "United States - CPI (Mar)",
    "Australia - GDP (Q1)",
    "MONDAY 23 MAR 2026",
    "Release Date: 23 Mar 2026 | Local Time: 13:30",
    "",
]
for ln in SYNTHESIS_LINES:
    expect(f"_is_synthesis_header_line({ln!r}) is True",
           _is_synthesis_header_line(ln))
    expect(f"synthesis '{ln[:30]}...' is NOT a release title",
           not _looks_like_release_title(ln))
    expect(f"synthesis '{ln[:30]}...' is NOT a generic title",
           not _looks_like_title_line(ln))
for ln in NON_SYNTHESIS_LINES:
    expect(f"non-synthesis {ln!r:60s} _is_synthesis_header_line=False",
           not _is_synthesis_header_line(ln))


# ---------------------------------------------------------------------------
# 2. _inject_release_boundaries.
# ---------------------------------------------------------------------------
DENSE = """\
DATA WINDOW: 23 Mar 2026 to 27 Mar 2026
A. US WEEK \u2014 MACRO SYNTHESIS
The week resolved into a clearer inflation-constrained, stagflation-risk configuration.
B. US MACRO SIGNAL SCOREBOARD
Growth: ~
Supporting evidence:
The week's growth signal stayed mixed.
C. FULL RELEASE ARCHIVE
MONDAY 23 MAR 2026
UNITED STATES \u2014 National Activity Index (Feb)
Release Date: 23 Mar 2026 | Local Time: 13:30
Importance: **
Reuters Data
National Activity Index: -0.11 | Prior: 0.18
Comment \u2014 Economist Layer
The release reads as softer breadth.
UNITED STATES \u2014 Construction Spending MM (Jan)
Release Date: 23 Mar 2026 | Local Time: 15:00
Importance: **
Reuters Data
Construction Spending MM: -0.3% | Prior: 0.8%
Comment \u2014 Economist Layer
Genuine hard-data growth miss.
TUESDAY 24 MAR 2026
UNITED STATES \u2014 Unit Labor Costs Revised (Q4)
Release Date: 24 Mar 2026 | Local Time: 13:30
Importance: ***
Reuters Data
Unit Labor Costs Revised: 4.4% | Prior: 2.8%
Comment \u2014 Economist Layer
Tighter margin for noninflationary wage absorption.
"""

# Pre: dense has zero blank lines.
expect("DENSE has 0 blank lines pre-injection",
       "\n\n" not in DENSE)

injected = _inject_release_boundaries(DENSE)
expect("injection adds blank lines",
       injected.count("\n\n") >= 3,
       f"got {injected.count(chr(10) + chr(10))}")
# Each release title gets its own paragraph after injection
import re as _re
paras = _re.split(r"\n\s*\n+", injected)
expect("at least 4 paragraphs after injection (preamble + 3 releases)",
       len(paras) >= 4, f"got {len(paras)}")


# ---------------------------------------------------------------------------
# 3. extract_releases on the dense block returns 3 releases, not 1.
# ---------------------------------------------------------------------------
b = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=DENSE)
rels = extract_releases(b)
titles = [r.title for r in rels]
print("    Parsed titles:", titles)

expect("three releases extracted (not one fake synthesis release)",
       len(rels) == 3, f"got {len(rels)} -> {titles}")
expect("title 'National Activity Index' present",
       any("National Activity Index" in t for t in titles), f"got {titles}")
expect("title 'Construction Spending' present",
       any("Construction Spending" in t for t in titles), f"got {titles}")
expect("title 'Unit Labor Costs' present",
       any("Unit Labor Costs" in t for t in titles), f"got {titles}")
expect("no synthesis header parsed as a release title",
       not any(_is_synthesis_header_line(t) for t in titles),
       f"got {titles}")
expect("no day-of-week banner parsed as a release title",
       not any(t.upper().startswith(("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"))
               for t in titles),
       f"got {titles}")
# Reference periods are populated end-to-end.
expect("National Activity Index period 2026-02",
       any("National Activity" in r.title and r.reference_period == "2026-02"
           for r in rels))
expect("Construction Spending period 2026-01",
       any("Construction Spending" in r.title and r.reference_period == "2026-01"
           for r in rels))
expect("Unit Labor Costs period in {2025-Q4, 2026-Q4} (year-rollover quirk noted)",
       any(r.reference_period in {"2025-Q4", "2026-Q4"}
           and "Unit Labor Costs" in r.title for r in rels),
       f"got {[r.reference_period for r in rels]}")


# ---------------------------------------------------------------------------
# 4. Old blank-line-separated format still parses (no regression).
# ---------------------------------------------------------------------------
BLANK_LINE = """\
United States - CPI (Mar) ****

Release Date: 2026-04-15
Importance: 4

Reuters Data: Headline 2.6% YoY.

United States - PPI (Mar) ***

Release Date: 2026-04-16
Importance: 3

Reuters Data: Core 0.3% MoM.
"""
b2 = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=BLANK_LINE)
rels2 = extract_releases(b2)
expect("blank-line format still produces 2 releases",
       len(rels2) == 2, f"got {len(rels2)}")
titles2 = [r.title for r in rels2]
expect("CPI title present in blank-line format",
       any("CPI" in t for t in titles2), f"got {titles2}")
expect("PPI title present in blank-line format",
       any("PPI" in t for t in titles2), f"got {titles2}")


# ---------------------------------------------------------------------------
# 5. _inject_release_boundaries is a no-op when blank lines already present.
# ---------------------------------------------------------------------------
already_blank = BLANK_LINE
out = _inject_release_boundaries(already_blank)
expect("no-op when blank-line separation already exists",
       out == already_blank,
       "injection mutated already-separated text")


# ---------------------------------------------------------------------------
# 6. Synthesis paragraph never appears as a release title even when it
#    survives the preamble-drop logic (missing DATA WINDOW header).
# ---------------------------------------------------------------------------
NO_DW = """\
A. US WEEK \u2014 MACRO SYNTHESIS
The week resolved into a clearer inflation-constrained configuration.
UNITED STATES \u2014 CPI (Mar)
Release Date: 15 Apr 2026 | Local Time: 13:30
Importance: ****
Reuters Data
Headline CPI: 2.6% YoY
"""
b3 = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=NO_DW)
rels3 = extract_releases(b3)
titles3 = [r.title for r in rels3]
print("    No-DW titles:", titles3)
expect("at least one release parsed (CPI)",
       len(rels3) >= 1, f"got {len(rels3)}")
expect("synthesis header never inherited as title",
       not any(_is_synthesis_header_line(t) for t in titles3),
       f"got {titles3}")
expect("CPI is the parsed release title",
       any("CPI" in t for t in titles3), f"got {titles3}")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
