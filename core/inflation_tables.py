"""Monthly inflation breakdown tables (CPI / PCE) — calculation + pandas Styler formatting.

No streamlit import. The section module decides what rows exist and where the
data come from; this module turns rows into a table and styles it.

    rows = [TableRow(label, mm=<% m/m series>, weight=<float>, level=, bold=), ...]
    tbl  = build_inflation_table(rows, n_months=3)   # -> InflationTable (plain DataFrame inside)
    html = table_html(tbl)                            # -> styled HTML for st.markdown(..., unsafe_allow_html=True)

Conventions:
  - m/m is always computed on the full available history of an index (mm_pct),
    and only then are the latest `n_months` valid observations selected.
  - Values in the table are percentage points (0.16 == 0.16 %).
  - Residual rows (parent minus listed children) use fixed weights:
        mm_resid = (w_p * mm_p - sum(w_c * mm_c)) / (w_p - sum(w_c))
    which is exact for a fixed-weight (Laspeyres-type) aggregate and an
    approximation otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from . import transforms


# ---- Calculation --------------------------------------------------------------

# Month-on-month % change lives in core.transforms; kept here under its
# original name so existing callers (sections/inflation.py, sections/income.py)
# are unchanged.
mm_pct = transforms.mom_pct


def residual_mm(
    parent_mm: pd.Series, parent_w: float,
    children: Sequence[tuple[pd.Series, float]],
) -> tuple[pd.Series, float]:
    """m/m and weight of `parent minus children` (see module docstring)."""
    w_res = parent_w - sum(w for _, w in children)
    if w_res <= 0:
        raise ValueError("children weights exceed parent weight")
    num = parent_mm * parent_w
    for mm, w in children:
        num = num - mm.reindex(parent_mm.index) * w
    return num / w_res, w_res


@dataclass
class TableRow:
    label: str
    mm: Optional[pd.Series]          # % m/m, full history; None if unavailable
    weight: Optional[float]          # percent of the parent basket; None if unavailable
    level: int = 0                   # 0 = top aggregate, 1 = sub-aggregate, 2 = component
    bold: bool = False
    note: str = ""                   # e.g. why a row is missing


@dataclass
class InflationTable:
    df: pd.DataFrame                 # columns: Category, [Weight], <Mon YYYY> x n (latest first)
    dates: list                      # pd.Timestamp per month column, latest first
    levels: list = field(default_factory=list)
    bold: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    has_weight: bool = True

    @property
    def month_cols(self) -> list[str]:
        return [c for c in self.df.columns if c not in ("Category", "Weight")]


def build_inflation_table(
    rows: Sequence[TableRow], n_months: int = 3, include_weight: bool = True,
) -> InflationTable:
    """Assemble rows into a table showing the latest `n_months` valid months.

    The month columns are the last `n_months` non-NaN observations of the FIRST
    row (the headline aggregate), latest first. Other rows are aligned to those
    dates; a row with no value for a date shows NaN. With include_weight=False
    the Weight column is omitted (e.g. a real-spending table).
    """
    if not rows or rows[0].mm is None or rows[0].mm.dropna().empty:
        raise ValueError("first row (headline) must have data — it defines the month columns")
    dates = list(rows[0].mm.dropna().index[-n_months:][::-1])
    cols = [d.strftime("%b %Y") for d in dates]

    records = []
    for r in rows:
        vals = r.mm.reindex(dates).values if r.mm is not None else [np.nan] * len(dates)
        rec = [r.label]
        if include_weight:
            rec.append(r.weight if r.weight is not None else np.nan)
        records.append([*rec, *vals])
    columns = ["Category", *(["Weight"] if include_weight else []), *cols]
    df = pd.DataFrame(records, columns=columns)
    return InflationTable(
        df=df, dates=dates,
        levels=[r.level for r in rows], bold=[r.bold for r in rows], notes=[r.note for r in rows],
        has_weight=include_weight,
    )


# ---- Presentation (pandas Styler; still no streamlit) --------------------------

_POS_RGB = (214, 39, 40)     # red   -> inflation
_NEG_RGB = (44, 160, 44)     # green -> deflation
_MAX_ALPHA = 0.60            # keep text readable
_VMAX_PERCENTILE = 90        # symmetric bound = this percentile of |m/m| across the table
_VMAX_FLOOR = 0.30           # ... but never tighter than +/-0.30 pp


def shading_bound(values) -> float:
    """Symmetric colour bound used for every month column of a table.

    The bound is the 90th percentile of |m/m| over all displayed cells (floor
    0.30 pp), so intensity is comparable across the three months and across
    rows, while one energy swing of -6% does not wash out every other cell.
    Values beyond the bound saturate.
    """
    a = np.abs(np.asarray(values, dtype=float))
    a = a[~np.isnan(a)]
    if a.size == 0:
        return 0.0
    return float(max(np.percentile(a, _VMAX_PERCENTILE), _VMAX_FLOOR))


def _shade(v: float, vmax: float) -> str:
    if v is None or pd.isna(v) or not vmax:
        return ""
    a = min(abs(v) / vmax, 1.0) * _MAX_ALPHA
    if a < 0.04:                                    # near zero -> neutral
        return ""
    r, g, b = _POS_RGB if v > 0 else _NEG_RGB
    return f"background-color: rgba({r},{g},{b},{a:.2f})"


def format_inflation_table(tbl: InflationTable, font_px: int = 13):
    """Return a pandas Styler: hidden index, 2-decimals, indented labels, bold
    aggregates, symmetric red/green shading on the month columns only, and a
    highlighted latest-month column."""
    df = tbl.df
    month_cols = tbl.month_cols
    vmax = shading_bound(df[month_cols].values) if len(month_cols) else 0.0
    levels, bold = tbl.levels, tbl.bold

    styler = df.style
    num_cols = [*(["Weight"] if tbl.has_weight else []), *month_cols]
    styler = styler.format({c: "{:.2f}" for c in num_cols}, na_rep="–")

    # shading: month columns only
    shade = lambda v: _shade(v, vmax)  # noqa: E731
    styler = styler.map(shade, subset=month_cols) if hasattr(styler, "map") else styler.applymap(shade, subset=month_cols)

    # bold aggregates (whole row) + indentation of the label. padding-left is set
    # per cell for EVERY column because a table-wide `td {padding}` rule would
    # outrank the per-cell style (id+element beats id-only selector).
    def _row_css(row):
        weight = "font-weight: bold; " if bold[row.name] else ""
        indent = 6 + 18 * levels[row.name]
        return [weight + (f"padding-left: {indent}px" if j == 0 else "padding-left: 10px") for j in range(len(row))]
    styler = styler.apply(_row_css, axis=1)

    latest = 2 if tbl.has_weight else 1  # positional index of the latest-month column
    styler = styler.set_table_styles([
        {"selector": "", "props": [("border-collapse", "collapse"), ("font-size", f"{font_px}px"),
                                   ("font-family", "Source Sans Pro, Segoe UI, Arial, sans-serif")]},
        {"selector": "th", "props": [("background-color", "#f3f4f6"), ("color", "#222"), ("font-weight", "600"),
                                     ("padding", "5px 10px"), ("border-bottom", "1px solid #bbb"), ("text-align", "right")]},
        {"selector": "th.col0", "props": [("text-align", "left")]},
        {"selector": "td", "props": [("padding-top", "3px"), ("padding-bottom", "3px"), ("padding-right", "10px"),
                                     ("border-bottom", "1px solid #e5e7eb"),
                                     ("text-align", "right"), ("white-space", "nowrap"), ("color", "#111")]},
        {"selector": "td.col0", "props": [("text-align", "left")]},
        {"selector": f"th.col{latest}", "props": [("border-left", "2px solid #444"), ("text-decoration", "underline")]},
        {"selector": f"td.col{latest}", "props": [("border-left", "2px solid #444")]},
    ])

    # hide the index (pandas >= 1.4: hide(); older: hide_index())
    styler = styler.hide(axis="index") if hasattr(styler, "hide") else styler.hide_index()
    return styler


def table_html(tbl: InflationTable, **kwargs) -> str:
    """Styled HTML string (works with pandas 1.x and 2.x)."""
    styler = format_inflation_table(tbl, **kwargs)
    return styler.to_html() if hasattr(styler, "to_html") else styler.render()
