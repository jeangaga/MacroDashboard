import sys
import os as _os
_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from core.normalize import normalize_release_name as N

tests = [
    # Generic CPI -> CPI / Core CPI
    ("US - CPI (Mar)",                     ("CPI / Core CPI", "Inflation", "High")),
    ("US - Core CPI YoY",                  ("CPI / Core CPI", "Inflation", "High")),
    ("Australia - CPI (Mar)",              ("CPI / Core CPI", "Inflation", "High")),
    # Institutional CPI - must NOT collapse with generic CPI
    ("UNITED STATES - Cleveland Fed CPI",  ("Cleveland Fed CPI / Median CPI", "Inflation", "High")),
    ("US - Cleveland Fed Median CPI",      ("Cleveland Fed CPI / Median CPI", "Inflation", "High")),
    ("US - Median CPI (Mar)",              ("Cleveland Fed CPI / Median CPI", "Inflation", "High")),
    # U Mich
    ("US - U Mich Sentiment / Inflation Expectations",
                                           ("U Mich Inflation Expectations", "Inflation", "High")),
    ("U Mich Sentiment Final",             ("U Mich Sentiment", "Growth", "High")),
    ("University of Michigan Inflation Expectations",
                                           ("U Mich Inflation Expectations", "Inflation", "High")),
    # NY Fed
    ("US - NY Fed Inflation Expectations", ("NY Fed Inflation Expectations", "Inflation", "High")),
    # Trimmed Mean (Australia)
    ("Australia - Trimmed Mean CPI",       ("Trimmed Mean CPI", "Inflation", "High")),
    # PCE / PPI
    ("US - PCE / Core PCE",                ("PCE / Core PCE", "Inflation", "High")),
    ("US - PPI Final Demand",              ("PPI", "Inflation", "High")),
    # Import prices
    ("US - Import Prices",                 ("Import Prices", "Inflation", "Medium")),
    # HICP
    ("Eurozone - HICP Final YY",           ("HICP", "Inflation", "High")),
    # Generic Inflation Expectations (non-institutional)
    ("Inflation Expectations Survey",      ("Inflation Expectations", "Inflation", "Medium")),
    # Low-confidence fallback
    ("Some bespoke survey",                ("Some bespoke survey", "", "Low")),
]
ok = fail = 0
for title, expected in tests:
    got = N(title)
    if got == expected:
        ok += 1
        print(f"  ok - {title!r:60s} -> {got}")
    else:
        fail += 1
        print(f"  FAIL - {title!r:60s} expected {expected} got {got}")
print(f"\n{ok} ok, {fail} fail")
