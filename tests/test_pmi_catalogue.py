"""Regression tests: PMI family naming, and catalogue dedup data loss.

Reported symptom: Country Release Catalogue -> US -> "PMI" showed 9
occurrences, and the two 3 Aug 2026 releases (ISM Manufacturing PMI and S&P
Global Manufacturing PMI Final) were missing while 31 Jul Chicago PMI showed.

Cause: every PMI title normalised to the single canonical name "PMI", so
`catalogue_key` was "US|PMI|2026-07" for all of them and `_catalogue_dedup`
kept only the first per month. On the real archive 41 US PMI releases were
displayed as 9 -- 32 silently dropped, with nothing in the UI to say so.

Two fixes, both locked here:
  1. `normalize_release_name` tells the PMI family apart.
  2. `_catalogue_dedup` no longer collapses two DIFFERENT releases that merely
     share a key inside one file. It still collapses the live/frozen parse of
     one event (different files) and exact duplicate events.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.normalize import catalogue_key, normalize_release_name  # noqa: E402
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


# ---------------------------------------------------------------------------
# 1. The PMI family are distinct recurring releases, not one bucket.
#    Titles below are copied verbatim from the real USD_WEEK.txt archive.
# ---------------------------------------------------------------------------
CASES = [
    ("UNITED STATES - Chicago PMI (Jul)",                          "Chicago PMI"),
    ("United States - Chicago PMI (May)",                          "Chicago PMI"),
    ("UNITED STATES - ISM Manufacturing PMI / Prices Paid (Jul)",  "ISM Manufacturing PMI"),
    ("US - ISM Manufacturing PMI (Jan)",                           "ISM Manufacturing PMI"),
    ("United States - ISM Manufacturing PMI / ISM Mfg Prices Paid (Mar)",
                                                                   "ISM Manufacturing PMI"),
    ("UNITED STATES - ISM Services PMI (Jul)",                     "ISM Services PMI"),
    ("US - ISM Non-Manufacturing PMI (Jan)",                       "ISM Services PMI"),
    ("United States - ISM N-Mfg PMI / Business Activity (May)",    "ISM Services PMI"),
    ("UNITED STATES - S&P Global Manufacturing PMI Final (Jul)",   "Manufacturing PMI"),
    ("United States - S&P Global Mfg PMI Final (May)",             "Manufacturing PMI"),
    ("UNITED STATES - S&P Global Flash Manufacturing / Services / Composite PMI (Jul)",
                                                                   "Manufacturing PMI Flash"),
    ("UNITED STATES - S&P Global Manufacturing / Services / Composite PMI Flash (Aug)",
                                                                   "Manufacturing PMI Flash"),
    ("UNITED STATES - S&P Global Services / Composite PMI Final (Jul)",
                                                                   "Services PMI"),
    ("US - S&P Global Services PMI Final (Jan)",                   "Services PMI"),
    ("US - S&P Global Composite PMI Final (Jan)",                  "Composite PMI"),
]
for title, want in CASES:
    got, _theme, _conf = normalize_release_name(title)
    expect(f"{title[:52]!r} -> {want}", got == want, f"got {got!r}")

# All stay High-confidence Growth, so the catalogue's "known releases only"
# filter doesn't start hiding them.
for title, _want in CASES:
    _n, theme, conf = normalize_release_name(title)
    expect(f"{title[:38]!r} stays Growth/High",
           theme == "Growth" and conf == "High", f"got {theme}/{conf}")

# The generic fallbacks still work.
expect("bare 'PMI' still normalises to PMI",
       normalize_release_name("Country - PMI (Jul)")[0] == "PMI",
       f"got {normalize_release_name('Country - PMI (Jul)')[0]!r}")
expect("'Purchasing Managers Index' still normalises to PMI",
       normalize_release_name("Country - Purchasing Managers Index")[0] == "PMI")
expect("non-PMI ISM line still normalises to ISM",
       normalize_release_name("US - ISM Prices Paid")[0] == "ISM",
       f"got {normalize_release_name('US - ISM Prices Paid')[0]!r}")


# The point of the whole fix: the July 2026 titles no longer share a key.
def _rel(title, date, imp, fn="USD_WEEK.txt", period="2026-07"):
    return Release(source_file=fn, block_stem="USD_WEEK", region="USD",
                   kind="frozen_week", title=title, importance=imp,
                   date_str=date, countries=["US"], themes=[], raw_block="",
                   reference_period=period)


july = [
    _rel("UNITED STATES - Chicago PMI (Jul)", "31 Jul 2026", "**"),
    _rel("UNITED STATES - ISM Manufacturing PMI / Prices Paid (Jul)", "3 Aug 2026", "****"),
    _rel("UNITED STATES - S&P Global Manufacturing PMI Final (Jul)", "3 Aug 2026", "***"),
    _rel("UNITED STATES - ISM Services PMI (Jul)", "5 Aug 2026", "***"),
    _rel("UNITED STATES - S&P Global Services / Composite PMI Final (Jul)", "5 Aug 2026", "***"),
]
keys = [catalogue_key(r) for r in july]
expect("the five July PMI releases get five distinct catalogue keys",
       len(set(keys)) == 5, f"got {keys}")


# ---------------------------------------------------------------------------
# 2. _catalogue_dedup must never silently drop a different release.
# ---------------------------------------------------------------------------
import streamlit_app  # noqa: E402

dedup = streamlit_app._catalogue_dedup

kept = dedup(july)
expect("all five July PMI releases survive dedup", len(kept) == 5,
       f"got {len(kept)}: {[r.title[:34] for r in kept]}")
expect("the 3 Aug ISM release is kept",
       any("ISM Manufacturing" in r.title for r in kept))
expect("the 3 Aug S&P release is kept",
       any("S&P Global Manufacturing" in r.title for r in kept))

# Even where the normalizer CANNOT tell two releases apart, they must not
# vanish: same file, same key, different event. A duplicate-looking row is a
# far better failure than a missing release.
a = _rel("United Kingdom - Nationwide House Price Index (Jun)", "1 Jul 2026", "**")
b = _rel("United Kingdom - Halifax House Prices MM / YY (Jun)", "7 Jul 2026", "**")
expect("the two house-price releases DO share a key (normalizer can't split them)",
       catalogue_key(a) == catalogue_key(b),
       f"{catalogue_key(a)} vs {catalogue_key(b)}")
expect("...but dedup keeps BOTH (same file, different event)",
       len(dedup([a, b])) == 2, f"got {len(dedup([a, b]))}")

# Cross-file: the same event parsed live and frozen must still collapse,
# frozen first. This is the behaviour the dedup exists for.
frozen = _rel("United States - Retail Sales MM (Mar)", "21 Apr 2026", "****",
              period="2026-03")
live = _rel("US - Retail Sales (Mar)", "22 Apr 2026", "***",
            fn="USD_WEEK_LIVE_MACRO.txt", period="2026-03")
out = dedup([frozen, live])
expect("live duplicate of one event still collapses across files",
       len(out) == 1, f"got {len(out)}")
expect("frozen wins the collapse", bool(out) and out[0] is frozen)

# An exact duplicate event inside one file still collapses.
dup = _rel("UNITED STATES - Chicago PMI (Jul)", "31 Jul 2026", "**")
expect("an exact duplicate event in one file still collapses",
       len(dedup([july[0], dup])) == 1, f"got {len(dedup([july[0], dup]))}")

# Period-less releases are still never collapsed.
no_period = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD",
    kind="frozen_week", title="US - Jobless Claims", importance="****",
    date_str="17 Apr 2026", countries=["US"], themes=[], raw_block="",
    reference_period=None,
)
expect("period-less releases are never collapsed",
       len(dedup([no_period, no_period])) == 2,
       f"got {len(dedup([no_period, no_period]))}")

expect("dedup is safe on empty / None",
       dedup([]) == [] and dedup(None) == [])


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
