"""BEA API client (NIPA underlying-detail tables) with on-disk caching.

Used for data FRED carries only at quarterly frequency: the monthly detailed
PCE price indexes (NIPA table 2.4.4U, BEA table id "U20404") and the matching
current-dollar expenditures (2.4.5U, "U20405") used as expenditure-share
weights.

Same joblib cache layer as core/fred_client and core/bls_client, and the same
key resolution (core.config.get_bea_key). The key is read inside the cached
function so it is never part of the cache key.

Public API:
    get_table_series(table, codes, start_year, end_year=None) -> pd.DataFrame
        Monthly values for the given BEA SeriesCodes, one column per code,
        indexed by month start. Values are floats (BEA's thousands separators
        removed). Missing codes simply produce no column.

BEA limits: 100 requests / minute, 100 MB / minute, 30 errors / minute.
One request per (table, year-range) here; the whole table is fetched and
filtered locally, which is what BEA recommends for underlying-detail tables.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd
import requests
from joblib import Memory

from . import config


BEA_URL = "https://apps.bea.gov/api/data/"
DATASET = "NIUnderlyingDetail"

TABLE_PCE_PRICE = "U20404"      # NIPA 2.4.4U  price indexes, monthly (2017=100)
TABLE_PCE_NOMINAL = "U20405"    # NIPA 2.4.5U  current-dollar expenditures, monthly ($mn SAAR)
TABLE_PCE_REAL = "U20406"       # NIPA 2.4.6U  real expenditures, monthly ($mn chained 2017, SAAR)

_memory = Memory(config.CACHE_DIR, verbose=0)


@_memory.cache
def _fetch_table_raw(table: str, years: str) -> list[dict]:
    """Cached GET of one underlying-detail table for a comma-separated year list."""
    params = {
        "UserID": config.get_bea_key(),
        "method": "GetData",
        "datasetname": DATASET,
        "TableName": table,
        "Frequency": "M",
        "Year": years,
        "ResultFormat": "JSON",
    }
    r = requests.get(BEA_URL, params=params, timeout=120)
    r.raise_for_status()
    body = r.json().get("BEAAPI", {})
    results = body.get("Results", {})
    err = results.get("Error") or body.get("Error")
    if err:
        raise RuntimeError(f"BEA API error: {err.get('APIErrorCode')} — {err.get('APIErrorDescription')}")
    data = results.get("Data")
    if not data:
        raise RuntimeError(f"BEA API returned no data for table {table}, years {years}")
    return data


def _to_float(v: str) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _period_to_ts(p: str) -> Optional[pd.Timestamp]:
    # BEA monthly periods look like "2026M07"
    if "M" not in p:
        return None
    y, m = p.split("M")
    return pd.Timestamp(year=int(y), month=int(m), day=1)


def get_table_series(
    table: str,
    codes: dict[str, str],
    start_year: int,
    end_year: Optional[int] = None,
) -> pd.DataFrame:
    """Monthly values for {name: SeriesCode} from `table`, indexed by month start."""
    end_year = end_year if end_year is not None else dt.date.today().year
    years = ",".join(str(y) for y in range(start_year, end_year + 1))
    data = _fetch_table_raw(table, years)

    code_to_name = {v: k for k, v in codes.items()}
    rows = []
    for d in data:
        name = code_to_name.get(d.get("SeriesCode"))
        if name is None:
            continue
        ts = _period_to_ts(d.get("TimePeriod", ""))
        val = _to_float(d.get("DataValue"))
        if ts is None or val is None:
            continue
        rows.append({"Date": ts, "Name": name, "Value": val})

    if not rows:
        raise RuntimeError(f"none of the requested series codes were found in BEA table {table}")

    return (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["Date", "Name"])
        .pivot(index="Date", columns="Name", values="Value")
        .sort_index()
    )


def clear_cache() -> None:
    """Wipe this client's on-disk cache entries (BEA only)."""
    _fetch_table_raw.clear(warn=False)
