"""BLS Public Data API (v2) client with on-disk caching.

Used for data FRED does not carry: the monthly *relative importance* weights
attached to the NSA CPI-U series (returned as "aspects" by the BLS API).

Same joblib cache layer as core/fred_client so behaviour is identical in
Streamlit, Colab, and a plain REPL. The API key is read inside the cached
function via core.config, so it is never part of the cache key.

Public API:
    get_indexes(series_map, start_year, end_year=None) -> pd.DataFrame
        Monthly index levels, one column per name in `series_map`.

    get_relative_importance(series_map, start_year, end_year=None) -> pd.DataFrame
        Monthly "Relative Importance" aspect values (percent of the CPI basket),
        one column per name in `series_map`.

BLS limits (with a registration key): 50 series and 20 years per request,
500 requests per day. Both fetchers issue one request per call.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd
import requests
from joblib import Memory

from . import config


BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

_memory = Memory(config.CACHE_DIR, verbose=0)


@_memory.cache
def _fetch_raw(series_ids: tuple[str, ...], start_year: int, end_year: int, aspects: bool) -> dict:
    """Cached raw POST to the BLS API. Raises on HTTP or API-level failure."""
    payload = {
        "seriesid": list(series_ids),
        "startyear": str(start_year),
        "endyear": str(end_year),
        "registrationkey": config.get_bls_key(),
    }
    if aspects:
        payload["aspects"] = True

    r = requests.post(BLS_URL, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()

    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API error: {data.get('status')} — {data.get('message')}")
    return data


def _resolve_end_year(end_year: Optional[int]) -> int:
    return end_year if end_year is not None else dt.date.today().year


def _month_start(obs: dict) -> Optional[pd.Timestamp]:
    """Return the month-start Timestamp for an observation, or None for non-monthly periods."""
    period = obs.get("period", "")
    if not period.startswith("M"):
        return None
    month = int(period[1:])
    if month < 1 or month > 12:  # M13 = annual average
        return None
    return pd.Timestamp(year=int(obs["year"]), month=month, day=1)


def get_indexes(
    series_map: dict[str, str],
    start_year: int,
    end_year: Optional[int] = None,
) -> pd.DataFrame:
    """Monthly index levels for {name: bls_series_id}, indexed by month start."""
    end_year = _resolve_end_year(end_year)
    data = _fetch_raw(tuple(series_map.values()), start_year, end_year, aspects=False)
    id_to_name = {v: k for k, v in series_map.items()}

    rows = []
    for series in data["Results"]["series"]:
        name = id_to_name.get(series["seriesID"], series["seriesID"])
        for obs in series.get("data", []):
            date = _month_start(obs)
            if date is None or obs.get("value") in (None, "", "-"):
                continue
            rows.append({"Date": date, "Category": name, "Value": float(obs["value"])})

    if not rows:
        raise RuntimeError("BLS returned no monthly observations for the requested series.")

    return (
        pd.DataFrame(rows)
        .pivot(index="Date", columns="Category", values="Value")
        .sort_index()
    )


def get_relative_importance(
    series_map: dict[str, str],
    start_year: int,
    end_year: Optional[int] = None,
) -> pd.DataFrame:
    """Monthly BLS 'Relative Importance' (percent of basket) for {name: bls_series_id}.

    Only the NSA CPI-U series (CUUR...) carry this aspect.
    """
    end_year = _resolve_end_year(end_year)
    data = _fetch_raw(tuple(series_map.values()), start_year, end_year, aspects=True)
    id_to_name = {v: k for k, v in series_map.items()}

    rows = []
    for series in data["Results"]["series"]:
        name = id_to_name.get(series["seriesID"], series["seriesID"])
        for obs in series.get("data", []):
            date = _month_start(obs)
            if date is None:
                continue
            for aspect in obs.get("aspects", []):
                if aspect.get("name", "").strip().lower() != "relative importance":
                    continue
                value = aspect.get("value")
                if value in (None, "", "-"):
                    continue
                rows.append({"Date": date, "Category": name, "Weight": float(value)})

    if not rows:
        raise RuntimeError(
            "BLS returned no 'Relative Importance' aspects. "
            "Check that the series are NSA CPI-U (CUUR...) and that aspects=True was sent."
        )

    return (
        pd.DataFrame(rows)
        .pivot(index="Date", columns="Category", values="Weight")
        .sort_index()
    )


def clear_cache() -> None:
    """Wipe this client's on-disk cache entries (BLS only)."""
    _fetch_raw.clear(warn=False)
