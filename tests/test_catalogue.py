"""End-to-end test of the Country Release Catalogue feature.

Builds synthetic Australia releases (CPI, Labour Force, RBA Decision, Retail
Sales, Trade Balance), runs them through extract_releases + normalize, then
verifies grouping/aggregation matches what the catalogue tab will display.
"""
import sys, datetime as _dt
import os as _os
_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.parsers import Block, extract_releases
from core.normalize import normalize_release_name
from utils.text import parse_release_date


SAMPLE_AU = """\
Australia - CPI (Mar)

Release Date: 2026-04-23 ****
Importance: 4

Reuters Data: Headline CPI 2.7% YoY.

Australia - CPI (Feb)

Release Date: 2026-03-26 ***
Importance: 3

Reuters Data: Earlier print 2.5% YoY.

Australia - CPI (Jan)

Release Date: 2026-02-25 ***
Importance: 3

Australia - Labour Force (Mar)

Release Date: 2026-04-17 ****
Importance: 4

Reuters Data: Unemployment ticked up to 4.1%.

Australia - Labour Force (Feb)

Release Date: 2026-03-20 ***

Australia - Labour Force (Jan)

Release Date: 2026-02-13 ***

Australia - Retail Sales MM (Mar)

Release Date: 2026-04-09 ***
Importance: 3

RBA Decision (Apr)

Release Date: 2026-04-01 ****
Importance: 4

RBA Minutes (Apr)

Release Date: 2026-04-15 ***
Importance: 3
"""

block = Block(stem="AUD_WEEK", source_file="aud_week.md", raw_text=SAMPLE_AU)
rels = extract_releases(block)
print(f"Total parsed releases: {len(rels)}")
for r in rels:
    print(f"  {r.title!r}  | {r.importance} | {r.date_str} | countries={r.countries}")

# All AU-tagged releases should have countries = ['Australia']
au_rels = [r for r in rels if "Australia" in (r.countries or [])]
assert len(au_rels) >= 7, f"expected at least 7 AU releases, got {len(au_rels)}"

# Group by normalized name like the catalogue would
groups = {}
meta = {}
for r in au_rels:
    name, theme, conf = normalize_release_name(r.title)
    if not name:
        continue
    groups.setdefault(name, []).append(r)
    if name not in meta:
        meta[name] = (theme, conf)

print("\nGrouped by normalized name:")
for name, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    theme, conf = meta[name]
    rs_sorted = sorted(rs, key=lambda r: parse_release_date(r.date_str) or _dt.date.min, reverse=True)
    print(f"  {name:25s} theme={theme:10s} conf={conf:6s} occurrences={len(rs)}  latest={rs_sorted[0].date_str}")

# Check expected groupings
assert "CPI / Core CPI" in groups and len(groups["CPI / Core CPI"]) == 3, "CPI / Core CPI should have 3 occurrences"
assert "Labour Force" in groups and len(groups["Labour Force"]) == 3
assert "Retail Sales" in groups and len(groups["Retail Sales"]) == 1
# Note: RBA Decision/Minutes don't have explicit Australia in title - they get tagged
# via the country alias 'RBA' that COUNTRY_ALIASES has under Australia
# So they should be grouped too if the country detection picks them up.

# Verify latest for CPI is 2026-04-23
cpi_latest = sorted(groups["CPI / Core CPI"], key=lambda r: parse_release_date(r.date_str) or _dt.date.min, reverse=True)[0]
assert cpi_latest.date_str == "2026-04-23", f"expected CPI latest 2026-04-23, got {cpi_latest.date_str}"
assert cpi_latest.importance == "****", f"expected ****, got {cpi_latest.importance}"
print("\n[catalogue] grouping & latest-pick verified.")

# Streamlit module imports cleanly
import importlib
import streamlit_app  # noqa: F401
print("[catalogue] streamlit_app imports cleanly.")

print("\nAll catalogue checks passed.")
