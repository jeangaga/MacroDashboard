"""Notebook code export — one registry entry per dashboard chart / table.

UI-neutral: no Streamlit import, no network access, no code execution. app.py
reads this registry to render the "</> Code" control next to each chart and
to generate the master TXT download.

Snippets assume the companion notebook has already run:

    import pandas as pd
    import numpy as np
    import plotly.express as px
    import plotly.graph_objects as go
    from core import config, transforms
    from core.fred_client import get_series, get_frame
    from core.bls_client import get_indexes, get_relative_importance
    from core.bea_client import get_table_series
    config.set_api_key("FRED_API_KEY", ...)   # + BLS / BEA keys

and therefore repeat neither imports nor keys.

Two snippet types (see the `builder` field):
  * direct core extraction  — get_frame / get_series + core.transforms,
    for charts whose calculation is one or two transparent steps;
  * section frame-builder   — `from sections.<x> import <fn>` for multi-stage
    derived datasets, so the notebook gets EXACTLY the dashboard numbers.

chart_id convention: "<section prefix>_<entry id>" where the entry id is the
"id" of the chart in sections/<x>.build(); prefixes are labor / inflation /
income. Table sub-tabs append "_<tab>" (e.g. inflation_detail_pce).
"""

from __future__ import annotations

from typing import Optional

MASTER_FILENAME = "macro_dashboard_notebook_snippets.txt"

SECTION_ORDER = ["Labor", "Inflation", "Wages & Income"]
SECTION_PREFIX = {"labor": "Labor", "inflation": "Inflation", "income": "Wages & Income"}

LABOR_START = "2022-01-01"        # dashboard sidebar defaults — adjust in the notebook
INFLATION_START = "2015-08-01"
INCOME_START = "2015-01-01"


def chart_id_for(section_key: str, entry_id: str, sub: Optional[str] = None) -> str:
    """Stable registry key for a section entry (and optional sub-tab label)."""
    base = entry_id if entry_id.startswith(section_key) else f"{section_key}_{entry_id}"
    return f"{base}_{sub.lower()}" if sub else base


# =============================================================================
# Registry
# =============================================================================
# Fields:
#   section    dashboard tab
#   title      chart title as shown on the dashboard
#   kind       "chart" | "table"
#   source     data source(s)
#   series     [(id, label), ...] — the actual FRED / BLS / BEA identifiers
#   transform  short list of the economic transformations applied
#   builder    "direct" or "sections.<module>.<function>"
#   frame      name of the DataFrame the snippet leaves behind
#   code       the snippet body (header is generated from the metadata)

CHART_CODE: dict[str, dict] = {}


def _add(chart_id: str, **spec) -> None:
    if chart_id in CHART_CODE:
        raise ValueError(f"duplicate chart_id {chart_id!r}")
    spec.setdefault("kind", "chart")
    spec.setdefault("builder", "direct")
    CHART_CODE[chart_id] = spec


# ---------------------------------------------------------------- LABOR ----

_add("labor_nfp_overview",
    section="Labor", title="NFP & Private Payrolls", source="FRED", frame="payrolls",
    series=[("PAYEMS", "Total Nonfarm Payrolls"), ("USPRIV", "Total Private Payrolls")],
    transform=["Monthly change (000s)", "3-month moving average of the change"],
    code=f'''
nfp = transforms.with_change_and_ma(get_series("PAYEMS"), "NFP", start_date="{LABOR_START}")
private = transforms.with_change_and_ma(get_series("USPRIV"), "Private", start_date="{LABOR_START}")
payrolls = nfp.join(private)                     # columns: NFP, NFP Δ, NFP Δ 3m MA, Private, ...
payrolls["Date"] = payrolls.index

fig = px.line(
    payrolls, x="Date",
    y=["NFP Δ", "NFP Δ 3m MA", "Private Δ", "Private Δ 3m MA"],
    title="NFP & Private Payrolls (m/m change, 000s)",
)
fig.show()
''')

_add("labor_claims",
    section="Labor", title="Unemployment Claims", source="FRED", frame="claims",
    series=[("ICSA", "Initial Claims (weekly, SA)"), ("CCSA", "Continued Claims (weekly, SA)")],
    transform=["12-week moving average of initial claims"],
    code=f'''
claims = get_frame({{"ICSA": "Initial Claims", "CCSA": "Continued Claims"}})
claims["Initial 12w MA"] = claims["Initial Claims"].rolling(12).mean()   # full history first
claims = claims.loc["{LABOR_START}":]
claims["Date"] = claims.index

fig = px.line(claims, x="Date", y=["Initial Claims", "Initial 12w MA"], title="Initial Claims")
fig.show()
fig2 = px.line(claims, x="Date", y="Continued Claims", title="Continued Claims")
fig2.show()
''')

_add("labor_jolts",
    section="Labor", title="JOLTS", source="FRED", frame="jolts",
    series=[("JTSJOL", "Job openings (level, ths)"), ("JTSHIR", "Hires rate (%)"),
            ("JTSQUR", "Quits rate (%)"), ("JTSLDR", "Layoffs & discharges rate (%)")],
    transform=["Levels as published (dashboard shows full history)"],
    code=f'''
jolts = get_frame({{
    "JTSJOL": "Job openings",
    "JTSHIR": "Hires rate",
    "JTSQUR": "Quits rate",
    "JTSLDR": "Layoffs rate",
}}).loc["{LABOR_START}":]
jolts["Date"] = jolts.index

fig = px.line(jolts, x="Date", y="Job openings", title="JOLTS — Job openings (ths)")
fig.show()
fig2 = px.line(jolts, x="Date", y=["Hires rate", "Quits rate", "Layoffs rate"], title="JOLTS — Rates (%)")
fig2.show()
''')

_add("labor_unemployment_jwg",
    section="Labor", title="Unemployment & Job-Worker Gap", source="FRED", frame="tightness",
    series=[("JTSJOL", "Job openings (ths)"), ("UNEMPLOY", "Unemployment level (ths)")],
    transform=["Job-worker ratio = job openings / unemployed"],
    code=f'''
tightness = get_frame({{"JTSJOL": "Job openings", "UNEMPLOY": "Unemployment"}})
tightness["Job-Worker Ratio"] = tightness["Job openings"] / tightness["Unemployment"]
tightness = tightness.loc["{LABOR_START}":]
tightness["Date"] = tightness.index

fig = px.line(tightness, x="Date", y="Unemployment", title="Unemployment (level, ths)")
fig.show()
fig2 = px.line(tightness, x="Date", y="Job-Worker Ratio", title="Job openings / unemployed")
fig2.show()
''')

_add("labor_nfp_sectors",
    section="Labor", title="NFP by Sector", source="FRED", frame="sectors",
    series="sections.labor.NFP_SECTOR_SERIES (17 CES payroll series: PAYEMS, USPRIV, USGOOD, ... USLAH)",
    transform=["Monthly change per sector", "3-month moving average of the change"],
    code=f'''
from sections.labor import NFP_SECTOR_SERIES      # [(FRED id, sector name), ...]

frames = []
for series_id, name in NFP_SECTOR_SERIES:
    df = transforms.with_change_and_ma(get_series(series_id), name, start_date="{LABOR_START}")
    frames.append(df[[f"{{name}} Δ 3m MA"]].rename(columns={{f"{{name}} Δ 3m MA": name}}))
sectors = pd.concat(frames, axis=1)              # 3m MA of the monthly change, one column per sector
sectors["Date"] = sectors.index

long = sectors.melt(id_vars="Date", var_name="Sector", value_name="Δ 3m MA (000s)")
fig = px.line(long, x="Date", y="Δ 3m MA (000s)", facet_col="Sector", facet_col_wrap=3,
              height=1200, title="NFP by Sector — 3m MA of monthly change")
fig.update_yaxes(matches=None)
fig.show()
''')

_add("labor_diffusion",
    section="Labor", title="Payroll Diffusion Index", source="FRED", frame="diffusion",
    series="sections.labor.DIFFUSION_EXTENDED (17 sectors) / DIFFUSION_BASIC (10 sectors)",
    transform=["% of sectors with a positive 3-month change", "6-month moving average",
               "transforms.diffusion_index (sectors whose FRED id is unavailable are skipped, as on the dashboard)"],
    code='''
from core.fred_client import get_series_safe          # returns None for an unavailable id
from sections.labor import DIFFUSION_EXTENDED         # {sector name: FRED id}; DIFFUSION_BASIC for 10 sectors

series = {name: get_series_safe(sid, freq="MS") for name, sid in DIFFUSION_EXTENDED.items()}
levels = transforms.assemble_levels({name: s for name, s in series.items() if s is not None})
diffusion = transforms.diffusion_index(levels, months_change=3, ma_months=6, start_date="2015-01-01")
diffusion["Date"] = diffusion.index

fig = px.line(diffusion, x="Date", y=["Diffusion (%)", "Diffusion MA"],
              title="Payroll Diffusion Index — % of sectors with positive 3m job growth")
fig.show()
''')

_add("labor_cyclical",
    section="Labor", title="Cyclical vs Non-Cyclical NFP", source="FRED", frame="cyclical",
    series=[("PAYEMS", "Total Nonfarm"), ("USGOVT", "Government"), ("USEHS", "Education & Health")],
    transform=["Cyclical Δ = ΔNFP − ΔGov − ΔEdu&Health; Non-cyclical Δ = ΔGov + ΔEdu&Health",
               "transforms.cyclical_split"],
    code=f'''
cyclical = transforms.cyclical_split(get_series("PAYEMS"), get_series("USGOVT"), get_series("USEHS"))
cyclical = cyclical.loc["{LABOR_START}":].dropna(subset=["Cyclical Δ", "Non-cyclical Δ"])

fig = go.Figure()
fig.add_bar(x=cyclical.index, y=cyclical["Cyclical Δ"], name="Cyclical (NFP − Gov − Edu&Health)")
fig.add_bar(x=cyclical.index, y=cyclical["Non-cyclical Δ"], name="Non-cyclical (Gov + Edu&Health)")
fig.add_scatter(x=cyclical.index, y=cyclical["NFP Δ"], name="Headline NFP Δ", mode="lines")
fig.update_layout(barmode="relative", title="NFP Contribution — Cyclical vs Non-Cyclical (m/m, 000s)")
fig.show()
''')


# ------------------------------------------------------------ INFLATION ----

_CPI_LEVELS = '''cpi = get_frame({
    "CPIAUCSL": "CPI", "CPILFESL": "Core CPI", "CUSR0000SASLE": "Services CPI",
    "CUUR0000SACL1E": "Goods CPI", "CPIUFDSL": "Foods CPI",
})'''

_add("inflation_cpi_dashboard",
    section="Inflation", title="CPI Dashboard", source="FRED", frame="cpi_yoy",
    series=[("CPIAUCSL", "CPI"), ("CPILFESL", "Core CPI"), ("CUSR0000SASLE", "Services CPI"),
            ("CUUR0000SACL1E", "Goods CPI"), ("CPIUFDSL", "Foods CPI"), ("CUSR0000SAH1", "Shelter CPI"),
            ("CUSR0000SAM2", "Medical Svc CPI"), ("CUUR0000SAS4", "Transport Svc CPI"),
            ("CPIEDUSL", "Edu Comm Svc CPI"), ("CPIRECSL", "Recreation Svc CPI"), ("CPIOGSSL", "Other Svc CPI")],
    transform=["YoY % (12-month change) on full history, then trimmed",
               "3m annualized = linear (transforms.annualized_change, periods=3)"],
    code=f'''
cpi = get_frame({{
    "CPIAUCSL": "CPI", "CPILFESL": "Core CPI", "CUSR0000SASLE": "Services CPI",
    "CUUR0000SACL1E": "Goods CPI", "CPIUFDSL": "Foods CPI",
    "CUSR0000SAH1": "Shelter CPI", "CUSR0000SAM2": "Medical Svc CPI", "CUUR0000SAS4": "Transport Svc CPI",
    "CPIEDUSL": "Edu Comm Svc CPI", "CPIRECSL": "Recreation Svc CPI", "CPIOGSSL": "Other Svc CPI",
}})
cpi_yoy = cpi.apply(transforms.yoy_change) * 100                                   # YoY %, full history
cpi_3m = cpi[["CPI", "Core CPI"]].apply(transforms.annualized_change, periods=3) * 100   # linear 3m ann %
cpi_yoy, cpi_3m = cpi_yoy.loc["{INFLATION_START}":], cpi_3m.loc["{INFLATION_START}":]
cpi_yoy["Date"], cpi_3m["Date"] = cpi_yoy.index, cpi_3m.index

px.line(cpi_yoy, x="Date", y=["CPI", "Core CPI", "Services CPI", "Goods CPI", "Foods CPI"],
        title="US CPI — YoY (headline/core + major buckets)").show()
px.line(cpi_yoy, x="Date", y=["Services CPI", "Shelter CPI", "Medical Svc CPI", "Transport Svc CPI",
        "Edu Comm Svc CPI", "Recreation Svc CPI", "Other Svc CPI"], title="US Core Services CPI — YoY").show()
px.line(cpi_3m, x="Date", y=["CPI", "Core CPI"], title="US CPI — 3m annualized (linear)").show()
''')

_add("inflation_cpi_contribution",
    section="Inflation", title="Headline CPI — Contributions (6m annualized)", source="BLS API",
    builder="sections.inflation.cpi_contribution_frame", frame="cpi_contrib",
    series=[("CUSR0000SA0 / SA0L1E / SAF1 / SA0E", "SA CPI-U levels: headline, core, food, energy"),
            ("CUUR0000SA0 / SA0L1E / SAF1 / SA0E", "NSA relative-importance weights")],
    transform=["6m COMPOUND annualized rate (transforms.compound_annualized_change)",
               "Contribution = rate × weight at start of window (transforms.weighted_contributions)"],
    code='''
from sections.inflation import cpi_contribution_frame

cpi_contrib = cpi_contribution_frame().loc["2018":]        # columns: Core, Food, Energy (pp), Headline (%)

fig = go.Figure()
for col in ["Core", "Food", "Energy"]:
    fig.add_bar(x=cpi_contrib.index, y=cpi_contrib[col], name=col)
fig.add_scatter(x=cpi_contrib.index, y=cpi_contrib["Headline"], name="Headline CPI", mode="lines")
fig.update_layout(barmode="relative", title="Headline CPI — 6m annualized, contributions by component")
fig.show()
''')

_add("inflation_core_cpi_contribution",
    section="Inflation", title="Core CPI — Contributions (6m annualized)", source="BLS API",
    builder="sections.inflation.core_cpi_contribution_frame", frame="core_contrib",
    series=[("CUSR0000 SA0L1E / SACL1E / SASLE / SETA01 / SETA02 / SEHA / SEHC", "SA CPI-U levels"),
            ("CUUR0000 (same codes)", "NSA relative-importance weights, rescaled so Core = 100")],
    transform=["6m COMPOUND annualized rate", "Weighted contributions; residual groups = parent − listed parts"],
    code='''
from sections.inflation import core_cpi_contribution_frame

core_contrib = core_cpi_contribution_frame().loc["2018":]
groups = ["Used and New Cars", "Other Core Goods", "Rent + OER", "Other Core Services"]

fig = go.Figure()
for col in groups:
    fig.add_bar(x=core_contrib.index, y=core_contrib[col], name=col)
fig.add_scatter(x=core_contrib.index, y=core_contrib["Core"], name="Core CPI", mode="lines")
fig.update_layout(barmode="relative", title="Core CPI — 6m annualized, contributions by component")
fig.show()
''')

_add("inflation_cpi_headline_yoy",
    section="Inflation", title="CPI Headline — Major Buckets (YoY)", source="FRED", frame="cpi_yoy",
    series=[("CPIAUCSL", "CPI"), ("CPILFESL", "Core CPI"), ("CUSR0000SASLE", "Services CPI"),
            ("CUUR0000SACL1E", "Goods CPI"), ("CPIUFDSL", "Foods CPI")],
    transform=["YoY % on full history, then trimmed"],
    code=f'''
{_CPI_LEVELS}
cpi_yoy = (cpi.apply(transforms.yoy_change) * 100).loc["{INFLATION_START}":]
cpi_yoy["Date"] = cpi_yoy.index

fig = px.line(cpi_yoy, x="Date", y=["CPI", "Core CPI", "Services CPI", "Goods CPI", "Foods CPI"],
              title="Headline & Major CPI Components — YoY")
fig.show()
''')

_add("inflation_cpi_services_breakdown",
    section="Inflation", title="Services CPI — Sub-Category Breakdown (YoY)", source="FRED", frame="services_yoy",
    series=[("CUSR0000SASLE", "Services CPI"), ("CUSR0000SAH1", "Shelter"), ("CUSR0000SAM2", "Medical Care"),
            ("CUUR0000SAS4", "Transportation Services"), ("CPIEDUSL", "Education & Communication"),
            ("CPIRECSL", "Recreation"), ("CPIOGSSL", "Other Services")],
    transform=["YoY % on full history, then trimmed"],
    code=f'''
services = get_frame({{
    "CUSR0000SASLE": "Services CPI", "CUSR0000SAH1": "Shelter", "CUSR0000SAM2": "Medical Care",
    "CUUR0000SAS4": "Transportation Services", "CPIEDUSL": "Education & Communication",
    "CPIRECSL": "Recreation", "CPIOGSSL": "Other Services",
}})
services_yoy = (services.apply(transforms.yoy_change) * 100).loc["{INFLATION_START}":]
services_yoy["Date"] = services_yoy.index

fig = px.line(services_yoy, x="Date", y=list(services.columns), title="Core Services Breakdown — YoY")
fig.show()
''')

_add("inflation_cpi_momentum",
    section="Inflation", title="CPI Momentum — 3-Month Annualized", source="FRED", frame="cpi_3m",
    series=[("CPIAUCSL", "Headline CPI"), ("CPILFESL", "Core CPI")],
    transform=["3m annualized = LINEAR (transforms.annualized_change, periods=3): 3-month % change × 4"],
    code=f'''
cpi = get_frame({{"CPIAUCSL": "Headline CPI", "CPILFESL": "Core CPI"}})
cpi_3m = (cpi.apply(transforms.annualized_change, periods=3) * 100).loc["{INFLATION_START}":]
cpi_3m["Date"] = cpi_3m.index

fig = px.line(cpi_3m, x="Date", y=["Headline CPI", "Core CPI"], title="Inflation Momentum — 3m Annualized")
fig.show()
''')

_add("inflation_detail_pce",
    section="Inflation", title="PCE Inflation — Monthly Breakdown", kind="table", source="BEA API (+ FRED)",
    builder="sections.inflation.pce_table", frame="pce",
    series=[("BEA table U20404 (2.4.4U)", "PCE chain-type price indexes, monthly"),
            ("BEA table U20405 (2.4.5U)", "current-dollar PCE — expenditure-share weights"),
            ("IA001260M / LA001260M", "FRED: services ex energy & housing (Super-Core)")],
    transform=["m/m % (transforms.mom_pct) on full fetched history, latest 3 months shown"],
    code='''
from sections.inflation import pce_table

pce = pce_table().df          # Category | Weight | latest m/m % | previous | month -2
display(pce)
''')

_add("inflation_detail_cpi",
    section="Inflation", title="CPI Inflation — Monthly Breakdown", kind="table", source="BLS API",
    builder="sections.inflation.cpi_table", frame="cpi_detail",
    series=[("CUSR0000 + item code", "SA CPI-U levels for each row (see sections.inflation.CPI_TABLE_ROWS)"),
            ("CUUR0000 + item code", "Relative Importance weights (aspects=True)")],
    transform=["m/m % (transforms.mom_pct), latest 3 months", "Residual rows via core.inflation_tables.residual_mm"],
    code='''
from sections.inflation import cpi_table

cpi_detail = cpi_table().df   # Category | Weight | latest m/m % | previous | month -2
display(cpi_detail)
''')


# --------------------------------------------------------- WAGES & INCOME --

_add("income_wage_growth",
    section="Wages & Income", title="Wage Growth", source="FRED",
    builder="sections.income.wage_growth_frame", frame="wages",
    series=[("AHETPI", "Avg hourly earnings, production & nonsupervisory (monthly)"),
            ("ECIWAG", "ECI wages & salaries, private (quarterly)"),
            ("PRS85006101", "Nonfarm business compensation per hour (quarterly, already YoY %)")],
    transform=["AHE: 12-month YoY %", "ECI: 4-quarter YoY %", "Compensation: as published",
               "Quarterly series kept at native dates (no interpolation)"],
    code=f'''
from sections.income import wage_growth_frame

wages = wage_growth_frame().loc["{INCOME_START}":]      # monthly + quarterly on one date index, YoY %
wages["Date"] = wages.index

fig = px.line(wages.dropna(how="all", subset=wages.columns[:3]), x="Date", y=list(wages.columns[:3]),
              title="U.S. Wage Growth", markers=True)
fig.show()
''')

_add("income_ahe_momentum",
    section="Wages & Income", title="Average Hourly Earnings — Momentum", source="FRED", frame="ahe",
    series=[("AHETPI", "Avg hourly earnings, production & nonsupervisory")],
    transform=["YoY %", "6m and 3m annualized = LINEAR (transforms.annualized_change)"],
    code=f'''
ahe = get_frame({{"AHETPI": "AHE"}})
ahe["AHE — YoY"] = transforms.yoy_change(ahe["AHE"]) * 100
ahe["AHE — 6m annualized"] = transforms.annualized_change(ahe["AHE"], periods=6) * 100
ahe["AHE — 3m annualized"] = transforms.annualized_change(ahe["AHE"], periods=3) * 100
ahe = ahe.loc["{INCOME_START}":]
ahe["Date"] = ahe.index

fig = px.line(ahe, x="Date", y=["AHE — YoY", "AHE — 6m annualized", "AHE — 3m annualized"],
              title="Average Hourly Earnings — Momentum")
fig.show()
''')

_add("income_household_income",
    section="Wages & Income", title="Household Income Growth", source="FRED", frame="income",
    series=[("PI", "Personal Income ($bn SAAR)"), ("DSPI", "Disposable Personal Income"),
            ("DSPIC96", "Real Disposable Personal Income (chained 2017 $)")],
    transform=["YoY % (sidebar alternatives: transforms.annualized_change periods=3 / 6, linear)"],
    code=f'''
levels = get_frame({{"PI": "Personal Income", "DSPI": "Disposable Personal Income",
                    "DSPIC96": "Real Disposable Personal Income"}})
income = (levels.apply(transforms.yoy_change) * 100).loc["{INCOME_START}":]      # YoY %
# 3m / 6m annualized variants (linear, as on the dashboard):
#   levels.apply(transforms.annualized_change, periods=3) * 100
income["Date"] = income.index

fig = px.line(income, x="Date", y=list(levels.columns), title="Household Income Growth — YoY")
fig.show()
''')

_add("income_labor_income",
    section="Wages & Income", title="Aggregate Labor Income", source="FRED",
    builder="sections.income.labor_income_frame", frame="labor_income",
    series=[("USPRIV", "All employees, total private"), ("AWHAETP", "Avg weekly hours, total private"),
            ("CES0500000003", "Avg hourly earnings, all employees, total private")],
    transform=["Index = employment × hours × earnings, 100 at Mar 2006", "YoY %", "3m annualized (linear)"],
    code=f'''
from sections.income import labor_income_frame, labor_income_index

labor_income = labor_income_frame().loc["{INCOME_START}":]   # YoY and 3m annualized of the proxy index
labor_income["Date"] = labor_income.index
# level: labor_income_index()

fig = px.line(labor_income, x="Date", y=["Aggregate Labor Income — YoY", "Aggregate Labor Income — 3m annualized"],
              title="Aggregate Labor Income — Growth")
fig.show()
''')

_add("income_real_pce_table",
    section="Wages & Income", title="Real PCE Spending — Monthly Change", kind="table", source="BEA API",
    builder="sections.income.real_pce_table", frame="real_pce",
    series=[("BEA table U20406 (2.4.6U)", "real PCE by type, chained 2017 $ (see sections.income.REAL_PCE_ROWS)")],
    transform=["m/m % (transforms.mom_pct) on full fetched history, latest 3 months shown"],
    code='''
from sections.income import real_pce_table

real_pce = real_pce_table().df    # Category | latest m/m % | previous | month -2
display(real_pce)
''')

_add("income_real_pce_growth",
    section="Wages & Income", title="Real Consumer Spending — YoY vs 6-Month Annualized", source="FRED", frame="real_pce",
    series=[("PCEC96", "Real Personal Consumption Expenditures (chained 2017 $)")],
    transform=["YoY %", "6m annualized = COMPOUND (transforms.compound_annualized_change): ((x_t/x_t-6)^2 − 1) × 100"],
    code=f'''
real_pce = get_frame({{"PCEC96": "Real PCE"}})
real_pce["Real PCE — YoY"] = transforms.yoy_change(real_pce["Real PCE"]) * 100
real_pce["Real PCE — 6m annualized"] = transforms.compound_annualized_change(real_pce["Real PCE"], periods=6)
real_pce = real_pce.loc["{INCOME_START}":]
real_pce["Date"] = real_pce.index

fig = px.line(real_pce, x="Date", y=["Real PCE — YoY", "Real PCE — 6m annualized"],
              title="Real Consumer Spending — YoY vs 6-Month Annualized")
fig.show()
''')


# =============================================================================
# Rendering helpers (text only)
# =============================================================================

def _series_lines(series) -> list[str]:
    if isinstance(series, str):
        return [f"# Series: {series}"]
    out = ["# Series:"]
    for sid, label in series:
        out.append(f"#   {sid} — {label}")
    return out


def header(chart_id: str) -> str:
    """Compact metadata header generated from the registry entry."""
    spec = CHART_CODE[chart_id]
    lines = ["# " + "-" * 60, f"# {spec['title']}", f"# Dashboard: {spec['section']}", f"# Source: {spec['source']}"]
    lines += _series_lines(spec["series"])
    if spec.get("builder", "direct") != "direct":
        lines.append(f"# Builder: {spec['builder']}")
    if spec.get("transform"):
        lines.append("# Transform:")
        lines += [f"#   {t}" for t in spec["transform"]]
    lines.append("# " + "-" * 60)
    return "\n".join(lines)


def snippet(chart_id: str) -> str:
    """Header + code for one chart, ready to paste into the companion notebook."""
    return header(chart_id) + "\n\n" + CHART_CODE[chart_id]["code"].strip() + "\n"


def ids_for_section(section: str) -> list[str]:
    return [cid for cid, s in CHART_CODE.items() if s["section"] == section]


def master_text(section: Optional[str] = None) -> str:
    """All snippets (or one section's) in dashboard order, as one TXT."""
    bar = "=" * 60
    out = [bar, "MACRO DASHBOARD — NOTEBOOK CODE", bar, "",
           "These snippets assume the companion notebook has already imported the",
           "shared macro project core and configured API keys:", "",
           "    import pandas as pd, numpy as np",
           "    import plotly.express as px, plotly.graph_objects as go",
           "    from core import config, transforms",
           "    from core.fred_client import get_series, get_frame",
           "    from core.bls_client import get_indexes, get_relative_importance",
           "    from core.bea_client import get_table_series",
           '    config.set_api_key("FRED_API_KEY", ...)  # and BLS_API_KEY / BEA_API_KEY', "", ""]
    for sec in SECTION_ORDER:
        if section and sec != section:
            continue
        out += [bar, sec.upper(), bar, ""]
        for cid in ids_for_section(sec):
            out += ["-" * 60, CHART_CODE[cid]["title"].upper(), "-" * 60, "", snippet(cid), ""]
        out.append("")
    return "\n".join(out)
