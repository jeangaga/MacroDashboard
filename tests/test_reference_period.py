"""Regression tests for tasks #52-#56 (reference-period catalogue fix).

Locks the contract between the audit asks and the implementation:

- utils.text.extract_reference_period maps (Mar)->YYYY-MM, (Q1)->YYYY-QX,
  unrecognized title->None, missing release_date->None.
- core.parsers.Release exposes a `reference_period` field.
- core.parsers.extract_releases populates it end-to-end.
- core.normalize.catalogue_key returns "country|name|reference_period".
- core.normalize.release_key is UNCHANGED (still includes date+importance).
- streamlit_app's catalogue helpers sort/dedup by reference_period.
"""
import sys, datetime as _dt
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

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
# 1. utils.text.extract_reference_period
# ---------------------------------------------------------------------------
from utils.text import extract_reference_period as rp  # noqa: E402

RD_APR = _dt.date(2026, 4, 21)
RD_JAN = _dt.date(2026, 1, 8)

cases = [
    ("US - Retail Sales MM (Mar)",                RD_APR, "2026-03"),
    ("US - CPI (Mar)",                             RD_APR, "2026-03"),
    ("US - U Mich Sentiment Final (Apr)",          RD_APR, "2026-04"),
    ("US - PPI Final Demand (Apr P)",              RD_APR, "2026-04"),
    ("Australia - GDP (Q1)",                       RD_APR, "2026-Q1"),
    ("Australia - Trimmed Mean CPI (Q1) - YoY",    RD_APR, "2026-Q1"),
    ("US - NFP (Mar/Feb revision)",                RD_APR, "2026-03"),
    # Year-rollover: (Dec) released in Jan describes the prior year.
    ("US - CPI (Dec)",                             RD_JAN, "2025-12"),
    # No period token -> None.
    ("Eurozone - HICP Final YY",                   RD_APR, None),
    ("US - PCE / Core PCE",                        RD_APR, None),
    ("US - Jobless Claims",                        RD_APR, None),
    # Missing release_date -> None even when title carries a period.
    ("US - CPI (Mar)",                             None,   None),
    # Empty title -> None.
    ("",                                           RD_APR, None),
]
for title, rd, want in cases:
    got = rp(title, rd)
    same = (got == want)
    expect(f"rp({title!r}, {rd}) -> {want!r}", same,
           f"got {got!r}")


# ---------------------------------------------------------------------------
# 2. Release dataclass exposes reference_period.
# ---------------------------------------------------------------------------
from core.parsers import Release, Block, extract_releases  # noqa: E402
import dataclasses

field_names = [f.name for f in dataclasses.fields(Release)]
expect("Release.reference_period field exists",
       "reference_period" in field_names,
       f"fields={field_names}")
default_field = next(f for f in dataclasses.fields(Release)
                     if f.name == "reference_period")
expect("Release.reference_period defaults to None",
       default_field.default is None)


# ---------------------------------------------------------------------------
# 3. extract_releases populates reference_period end-to-end.
# ---------------------------------------------------------------------------
SAMPLE = """\
United States - Retail Sales MM (Mar) ****

Release Date: 2026-04-21
Importance: 4

Reuters Data: Headline 0.5% MoM.

Australia - GDP (Q1) ****

Release Date: 2026-05-04
Importance: 4

Reuters Data: 0.4% QoQ.

Eurozone - HICP Final YY ***

Release Date: 2026-04-17
Importance: 3

Reuters Data: HICP 2.4% YoY.
"""
b = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=SAMPLE)
rels = extract_releases(b)
expect("three releases parsed", len(rels) == 3, f"got {len(rels)}")

by_title = {r.title: r for r in rels}
retail = by_title.get("United States - Retail Sales MM (Mar)")
gdp    = by_title.get("Australia - GDP (Q1)")
hicp   = by_title.get("Eurozone - HICP Final YY")
expect("Retail Sales MM (Mar) -> 2026-03",
       retail is not None and retail.reference_period == "2026-03",
       f"got {retail.reference_period if retail else 'missing'}")
expect("GDP (Q1) -> 2026-Q1",
       gdp is not None and gdp.reference_period == "2026-Q1",
       f"got {gdp.reference_period if gdp else 'missing'}")
expect("HICP Final YY -> None (no period token)",
       hicp is not None and hicp.reference_period is None,
       f"got {hicp.reference_period if hicp else 'missing'}")


# ---------------------------------------------------------------------------
# 4. catalogue_key / release_key contract.
# ---------------------------------------------------------------------------
from core.normalize import catalogue_key, release_key  # noqa: E402

# Same period, different importance & file -> SAME catalogue key (frozen+live
# of the same Mar Retail Sales must collapse).
r_frozen = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD",
    kind="frozen_week",
    title="United States - Retail Sales MM (Mar)", importance="****",
    date_str="2026-04-21", countries=["US"], themes=[], raw_block="",
    reference_period="2026-03",
)
r_live = Release(
    source_file="USD_WEEK_LIVE_MACRO.txt", block_stem="USD_WEEK_LIVE_MACRO",
    region="USD", kind="live_week",
    title="US - Retail Sales (Mar)", importance="***",
    date_str="2026-04-22", countries=["US"], themes=[], raw_block="",
    reference_period="2026-03",
)
r_prev = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD",
    kind="frozen_week",
    title="US - Retail Sales (Feb)", importance="****",
    date_str="2026-03-17", countries=["US"], themes=[], raw_block="",
    reference_period="2026-02",
)
r_no_period = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD",
    kind="frozen_week",
    title="US - Jobless Claims", importance="****",
    date_str="2026-04-17", countries=["US"], themes=[], raw_block="",
    reference_period=None,
)

expect("catalogue_key ignores importance (frozen + live for same period collapse)",
       catalogue_key(r_frozen) == catalogue_key(r_live),
       f"{catalogue_key(r_frozen)} vs {catalogue_key(r_live)}")
expect("catalogue_key separates different reference periods",
       catalogue_key(r_frozen) != catalogue_key(r_prev),
       f"{catalogue_key(r_frozen)} vs {catalogue_key(r_prev)}")
expect("catalogue_key returns 'country|name|period'",
       catalogue_key(r_frozen) == "US|Retail Sales|2026-03",
       f"got {catalogue_key(r_frozen)!r}")
expect("catalogue_key empty string when reference_period is missing",
       catalogue_key(r_no_period) == "",
       f"got {catalogue_key(r_no_period)!r}")
expect("catalogue_key(None) is empty",
       catalogue_key(None) == "")

# release_key MUST NOT change behaviour. Frozen vs live with different
# importance must still be DISTINCT events.
expect("release_key still differs across importance/dates",
       release_key(r_frozen) != release_key(r_live),
       f"{release_key(r_frozen)} == {release_key(r_live)}")
expect("release_key includes date and importance",
       release_key(r_frozen) == "US|Retail Sales|2026-04-21|****",
       f"got {release_key(r_frozen)!r}")


# ---------------------------------------------------------------------------
# 5. streamlit_app catalogue helpers: sort by reference_period, dedup by
#    catalogue_key.
# ---------------------------------------------------------------------------
import streamlit_app  # noqa: E402

expect("_catalogue_sort_key callable",
       callable(getattr(streamlit_app, "_catalogue_sort_key", None)))
expect("_catalogue_dedup callable",
       callable(getattr(streamlit_app, "_catalogue_dedup", None)))

# Sort key prefers reference_period over publication date.
# r_late_apr_for_mar: Mar print published in late Apr (delayed)
# r_early_apr_for_mar: Apr print published early Apr (impossible IRL but
#   tests "period beats publication date")
# Real test: a delayed Mar revision must NOT outrank a fresh Apr print.
r_mar_delayed = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD",
    kind="frozen_week",
    title="US - CPI (Mar) revision", importance="****",
    date_str="2026-05-10", countries=["US"], themes=[], raw_block="",
    reference_period="2026-03",
)
r_apr_fresh = Release(
    source_file="USD_WEEK.txt", block_stem="USD_WEEK", region="USD",
    kind="frozen_week",
    title="US - CPI (Apr)", importance="****",
    date_str="2026-05-12", countries=["US"], themes=[], raw_block="",
    reference_period="2026-04",
)
sorted_desc = sorted([r_mar_delayed, r_apr_fresh],
                     key=streamlit_app._catalogue_sort_key, reverse=True)
expect("Apr print sorts latest even though Mar revision was published later",
       sorted_desc[0] is r_apr_fresh,
       f"got top={sorted_desc[0].title!r}")

# Dedup: frozen-first ordering keeps frozen, drops live duplicate of same period.
deduped = streamlit_app._catalogue_dedup([r_frozen, r_live, r_prev])
expect("dedup len = 2 (frozen + prev; live collapses)",
       len(deduped) == 2, f"got {len(deduped)}")
expect("dedup keeps frozen first (frozen-wins-over-live)",
       deduped[0] is r_frozen)
expect("dedup keeps the different-period release",
       deduped[1] is r_prev)

# Period-less releases are NEVER collapsed (catalogue_key empty).
deduped_np = streamlit_app._catalogue_dedup([r_no_period, r_no_period])
expect("dedup keeps both period-less releases (no false collapse)",
       len(deduped_np) == 2, f"got {len(deduped_np)}")


# ---------------------------------------------------------------------------
# 6. Catalogue tab no longer carries the dead `continue / continue` lines.
# ---------------------------------------------------------------------------
import inspect  # noqa: E402
src = inspect.getsource(streamlit_app.tab_country_release_catalogue)
# count "continue\n            continue" pattern
double = src.count("            continue\n            continue")
expect("no `continue / continue` dead duplicate in catalogue tab",
       double == 0, f"found {double} double-continue blocks")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
