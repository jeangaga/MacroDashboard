"""FRED API client with on-disk caching.

`joblib.Memory` is used as the cache layer because it works identically in
Streamlit, Colab, and a plain Python REPL — unlike `@st.cache_data`, which is
Streamlit-only and would break the "single source of truth" promise.

Public API:
    get_series(series_id, freq=None) -> pd.Series
        Cached fetch. Raises on failure.

    get_series_safe(series_id, freq=None) -> pd.Series | None
        Cached fetch that returns None instead of raising. Use when a missing
        series should be silently skipped (e.g. payroll diffusion index that
        unions many sector mnemonics).

    get_frame({"CPIENGSL": "Energy CPI", ...}, freq=None) -> pd.DataFrame
        Notebook-friendly wrapper around get_series: one column per series,
        human-readable column names, DatetimeIndex named "Date". Display
        names never touch the disk cache (which is keyed by series id only).

Keys: resolved by core.config (config.set_api_key(...) wins). Changing the
FRED key through set_api_key drops the cached Fred client so the next call
builds a new one.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional, Union

import pandas as pd
from fredapi import Fred
from joblib import Memory

from . import config


_memory = Memory(config.CACHE_DIR, verbose=0)


@lru_cache(maxsize=1)
def _fred() -> Fred:
    """Singleton FRED client, lazily constructed so importing this module
    doesn't fail if the key isn't set yet (e.g. during test collection)."""
    return Fred(api_key=config.get_fred_key())


def _on_key_change(name: str) -> None:
    """Drop the cached Fred client when FRED_API_KEY is (re)configured."""
    if name == "FRED_API_KEY":
        _fred.cache_clear()


config.register_key_listener(_on_key_change)


@_memory.cache
def _fetch_series_raw(series_id: str) -> pd.Series:
    """Cached raw fetch. Cache key is just the series_id — re-run by deleting
    the .cache/ directory or calling clear_cache()."""
    s = _fred().get_series(series_id)
    s.name = series_id
    return s


def get_series(series_id: str, freq: Optional[str] = None) -> pd.Series:
    """Fetch a FRED series (cached).

    Args:
        series_id: FRED mnemonic, e.g. 'PAYEMS'.
        freq: Optional pandas frequency string (e.g. 'MS' for month-start).
              If provided, the series is reindexed via .asfreq(freq).

    Returns:
        pd.Series indexed by date.
    """
    s = _fetch_series_raw(series_id).copy()
    if freq is not None:
        s = s.asfreq(freq)
    return s


def get_series_safe(series_id: str, freq: Optional[str] = None) -> Optional[pd.Series]:
    """Fetch a FRED series, returning None on any failure (including empty result).

    Use this when iterating over a dict of mnemonics where some may not exist
    (e.g. the diffusion index that mixes US* aliases and CESxxxxxxxx codes).
    """
    try:
        s = get_series(series_id, freq=freq)
        if s is None or len(s.dropna()) == 0:
            return None
        return s
    except Exception:
        return None


def get_frame(
    series: Union[str, dict[str, str], list[str]],
    freq: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch one or more FRED series into a DataFrame with readable column names.

    Args:
        series: a FRED id ("CPIENGSL"), a list of ids, or a {id: display name}
                mapping. Ids without a display name are used as-is.
        freq:   optional pandas frequency passed to get_series (e.g. "MS").

    Returns:
        DataFrame indexed by a DatetimeIndex named "Date", one float column per
        series, outer-joined on dates and sorted. Only get_series is called, so
        the disk cache is shared with the dashboard and display names never
        create extra cache entries.
    """
    if isinstance(series, str):
        mapping = {series: series}
    elif isinstance(series, dict):
        mapping = dict(series)
    else:
        mapping = {sid: sid for sid in series}
    if not mapping:
        raise ValueError("no series requested")

    cols = {name or sid: get_series(sid, freq=freq) for sid, name in mapping.items()}
    df = pd.concat(cols, axis=1).sort_index()
    df.index = pd.DatetimeIndex(df.index, name="Date")
    return df


def clear_cache() -> None:
    """Wipe this client's on-disk cache entries (FRED only; BLS/BEA have their own)."""
    _fetch_series_raw.clear(warn=False)
