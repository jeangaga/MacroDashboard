"""Regression test for the Catalogue 'Export to TXT' feature.

Locks the contract:
  - format_release_export builds a plain-text export with a header line,
    a count line, per-occurrence (date | importance + optional period,
    title, full raw_block), and a 50-dash separator between entries.
  - limit truncates to the first N (caller is responsible for sorting).
  - Header reflects 'Latest N of M' vs 'All N' depending on truncation.
  - raw_block is included verbatim (no cleaning).
  - _export_filename produces a filesystem-safe name.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit_app  # noqa: E402
from core.parsers import Release  # noqa: E402

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


def make(title, date_str, importance, raw, period=None):
    return Release(
        source_file="USD_WEEK.txt",
        block_stem="USD_WEEK",
        region="USD",
        kind="frozen_week",
        title=title,
        importance=importance,
        date_str=date_str,
        countries=["US"],
        themes=["Inflation"],
        raw_block=raw,
        reference_period=period,
    )


# Build 5 occurrences sorted by reference period descending (caller's job).
RELEASES = [
    make(
        "United States - CPI / Core CPI (Mar)", "10 Apr 2026", "****",
        "United States - CPI / Core CPI (Mar)\nRelease Date: 10 Apr 2026\n"
        "Importance: ****\nReuters Data\nHeadline CPI 2.6% YoY\nProfessional Market Commentary\nThe tape...",
        period="2026-03",
    ),
    make(
        "UNITED STATES - CPI / Core CPI (Feb)", "11 Mar 2026", "****",
        "UNITED STATES - CPI / Core CPI (Feb)\nRelease Date: 11 Mar 2026\n"
        "Importance: ****\nReuters Data\nCPI 2.4% YoY\nComment - Economist Layer\nbroadly steady",
        period="2026-02",
    ),
    make(
        "United States - CPI (Jan)", "13 Feb 2026", "****",
        "United States - CPI (Jan)\nRelease Date: 13 Feb 2026\nImportance: ****\nReuters Data\nCPI 2.5%",
        period="2026-01",
    ),
    make(
        "United States - CPI (Dec)", "12 Jan 2026", "***",
        "United States - CPI (Dec)\nRelease Date: 12 Jan 2026\nImportance: ***\nReuters Data\nCPI 2.7%",
        period="2025-12",
    ),
    make(
        "United States - CPI (Nov)", "10 Dec 2025", "***",
        "United States - CPI (Nov)\nRelease Date: 10 Dec 2025\nImportance: ***\nReuters Data\nCPI 2.6%",
        period="2025-11",
    ),
]


# ---------------------------------------------------------------------------
# 1. Default limit=4 truncates to 4 of 5 with "Latest 4 of 5 occurrences".
# ---------------------------------------------------------------------------
text = streamlit_app.format_release_export(
    "US", "CPI / Core CPI", RELEASES, limit=4,
)

expect("header line is 'US - CPI / Core CPI'",
       text.splitlines()[0] == "US - CPI / Core CPI",
       f"got {text.splitlines()[0]!r}")

expect("count line is 'Latest 4 of 5 occurrences'",
       "Latest 4 of 5 occurrences" in text,
       "missing count header")

# All 4 most-recent titles present (the Nov one is excluded).
for needle in ("Mar", "Feb", "Jan", "Dec"):
    expect(f"includes period {needle!r}",
           f"({needle})" in text or f"period 2026-{('0' + str({'Mar':3,'Feb':2,'Jan':1,'Dec':12}[needle]))[-2:]}" in text,
           "missing period")
expect("excludes Nov (the 5th, beyond limit)",
       "(Nov)" not in text and "period 2025-11" not in text,
       "Nov leaked into limited export")

# Separator appears between entries (3 separators for 4 entries).
sep = streamlit_app._EXPORT_SEPARATOR
expect("3 separators for 4 entries",
       text.count(sep) == 3,
       f"got {text.count(sep)}")

# Full raw_block included verbatim.
expect("verbatim raw_block: 'Reuters Data' phrase present 4 times",
       text.count("Reuters Data") == 4,
       f"got {text.count('Reuters Data')}")
expect("verbatim raw_block: prose 'Professional Market Commentary' present",
       "Professional Market Commentary" in text)
expect("verbatim raw_block: 'Comment - Economist Layer' present",
       "Comment - Economist Layer" in text)

# Date | importance line for the latest.
expect("date|importance|period line for latest",
       "10 Apr 2026 | **** | period 2026-03" in text,
       "missing structured first-line for latest entry")


# ---------------------------------------------------------------------------
# 2. limit=None -> "All 5 occurrences", everything included.
# ---------------------------------------------------------------------------
all_text = streamlit_app.format_release_export(
    "US", "CPI / Core CPI", RELEASES, limit=None,
)
expect("limit=None -> All 5 occurrences", "All 5 occurrences" in all_text)
expect("Nov entry now present",
       "(Nov)" in all_text and "period 2025-11" in all_text)
expect("4 separators for 5 entries",
       all_text.count(sep) == 4,
       f"got {all_text.count(sep)}")


# ---------------------------------------------------------------------------
# 3. limit larger than list -> "All N occurrences" (no fake truncation header).
# ---------------------------------------------------------------------------
big_text = streamlit_app.format_release_export(
    "US", "CPI / Core CPI", RELEASES, limit=20,
)
expect("limit > len -> 'All 5'",
       "All 5 occurrences" in big_text)
expect("limit > len: no 'of N' phrasing",
       " of " not in big_text.split("\n", 4)[2],
       f"got count line: {big_text.splitlines()[2]!r}")


# ---------------------------------------------------------------------------
# 4. Empty list -> "(no occurrences)".
# ---------------------------------------------------------------------------
empty_text = streamlit_app.format_release_export("US", "CPI", [], limit=4)
expect("empty list -> '(no occurrences)'",
       "(no occurrences)" in empty_text)
expect("empty list still has header",
       empty_text.startswith("US - CPI"))


# ---------------------------------------------------------------------------
# 5. _export_filename produces filesystem-safe names.
# ---------------------------------------------------------------------------
us_fname = streamlit_app._export_filename("US", "CPI / Core CPI")
expect("US CPI/Core CPI filename starts with 'US_CPI'",
       us_fname.startswith("US_CPI") and us_fname.endswith(".txt"),
       f"got {us_fname!r}")
expect("US CPI/Core CPI filename has no '/' or spaces",
       "/" not in us_fname and " " not in us_fname,
       f"got {us_fname!r}")
expect("Eurozone HICP -> Eurozone_HICP.txt",
       streamlit_app._export_filename("Eurozone", "HICP") == "Eurozone_HICP.txt")


# ---------------------------------------------------------------------------
# 6. Order is preserved verbatim from caller.
# ---------------------------------------------------------------------------
text = streamlit_app.format_release_export(
    "US", "CPI / Core CPI", RELEASES, limit=4,
)
mar_pos = text.find("(Mar)")
feb_pos = text.find("(Feb)")
jan_pos = text.find("(Jan)")
dec_pos = text.find("(Dec)")
expect("order preserved Mar -> Feb -> Jan -> Dec",
       mar_pos < feb_pos < jan_pos < dec_pos,
       f"positions Mar={mar_pos}, Feb={feb_pos}, Jan={jan_pos}, Dec={dec_pos}")


# ---------------------------------------------------------------------------
# 7. Output ends with a single trailing newline (consistent for downloads).
# ---------------------------------------------------------------------------
expect("export text ends with newline",
       text.endswith("\n") and not text.endswith("\n\n\n"),
       f"tail bytes: {text[-3:]!r}")


# ---------------------------------------------------------------------------
# 8. Release with no reference_period: period bit is omitted from the header.
# ---------------------------------------------------------------------------
no_period = [make(
    "United States - Jobless Claims", "17 Apr 2026", "***",
    "United States - Jobless Claims\nRelease Date: 17 Apr 2026\nImportance: ***\nReuters: 210k",
    period=None,
)]
np_text = streamlit_app.format_release_export("US", "Jobless Claims", no_period, limit=4)
expect("no period -> entry header has only 'date | importance'",
       "17 Apr 2026 | ***\n" in np_text and "period " not in np_text,
       f"got: {np_text!r}")


# ---------------------------------------------------------------------------
# 9. cc_export_limit is in _SCOPE_RESET_KEYS so scope-switch clears the choice.
# ---------------------------------------------------------------------------
expect("cc_export_limit in _SCOPE_RESET_KEYS",
       "cc_export_limit" in streamlit_app._SCOPE_RESET_KEYS,
       f"got {streamlit_app._SCOPE_RESET_KEYS}")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
