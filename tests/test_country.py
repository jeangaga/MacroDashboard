"""Regression test for country-aliasing and NFP rule.

Catches the bug where:
  - `US ` substring matched inside `Bonus ` and tagged UK releases as US
  - generic `payrolls?` regex collapsed UK labour-market headers (e.g.
    "HMRC Payrolls Change") into "Non-Farm Payrolls"
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.normalize import normalize_release_name
from utils.text import country_from_title, detect_countries

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


# --- The exact title that was misclassified in production ---
UK_LABOUR = (
    "United Kingdom - Claimant Count Unem Chng / ILO Unemployment Rate / "
    "Employment Change / Avg Wk Earnings 3M YY / Avg Earnings Ex-Bonus / "
    "HMRC Payrolls Change (Mar/Feb)"
)

c = country_from_title(UK_LABOUR)
expect("UK title -> ['UK']", c == ["UK"], f"got {c}")

c_all = detect_countries(UK_LABOUR)
expect("UK title detect_countries excludes US", "US" not in c_all, f"got {c_all}")
expect("UK title detect_countries includes UK", "UK" in c_all, f"got {c_all}")

name, theme, conf = normalize_release_name(UK_LABOUR)
expect("UK title NOT normalized as Non-Farm Payrolls",
       name != "Non-Farm Payrolls", f"got {(name, theme, conf)}")
expect("UK title normalized as Labour Force",
       name == "Labour Force", f"got {(name, theme, conf)}")

# --- Word-boundary country aliasing ---
expect("'Bonus' alone -> no country", country_from_title("Avg Earnings Ex-Bonus") == [])
expect("'BONUS' (caps) -> no country", country_from_title("EX-BONUS REPORT") == [])
expect("'BUSINESS' -> no country", country_from_title("BUSINESS Survey") == [])
expect("'USD CPI' -> no country (USD is not US)",
       country_from_title("USD CPI Mar") == [],
       f"got {country_from_title('USD CPI Mar')}")
expect("'US Treasury' -> ['US']", country_from_title("US Treasury auction") == ["US"])
expect("'U.S. CPI' -> ['US']", country_from_title("U.S. CPI Mar") == ["US"])
expect("'United States' -> ['US']",
       country_from_title("United States - CPI Mar") == ["US"])
expect("'Australia - CPI' -> ['Australia']",
       country_from_title("Australia - CPI (Mar)") == ["Australia"])
expect("'Eurozone - HICP' -> ['Eurozone']",
       country_from_title("Eurozone - HICP Final YY") == ["Eurozone"])
expect("'Switzerland - SNB' -> ['Switzerland']",
       country_from_title("Switzerland - SNB Decision") == ["Switzerland"])

# --- NFP rule must still match real NFP titles ---
n, _, _ = normalize_release_name("US - Non-Farm Payrolls")
expect("'US - Non-Farm Payrolls' -> Non-Farm Payrolls", n == "Non-Farm Payrolls", f"got {n}")
n, _, _ = normalize_release_name("NFP March")
expect("'NFP March' -> Non-Farm Payrolls", n == "Non-Farm Payrolls", f"got {n}")
n, _, _ = normalize_release_name("US - Non-Farm Payrolls / ADP / Avg Hourly Earnings")
expect("compound US NFP title -> Non-Farm Payrolls", n == "Non-Farm Payrolls", f"got {n}")

# --- Generic 'Payrolls' must NOT match NFP rule any more ---
n, _, _ = normalize_release_name("UK - HMRC Payrolls Change")
expect("'HMRC Payrolls Change' -> not NFP", n != "Non-Farm Payrolls", f"got {n}")

print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
