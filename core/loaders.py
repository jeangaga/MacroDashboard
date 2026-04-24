"""File loader with transparent local cache.

load_file(filename) -> LoadResult

1. Fresh cache hit if cache age < CACHE_TTL_SECONDS.
2. Otherwise try GitHub. Success -> write cache.
3. On network failure, serve stale cache if it exists.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.config import ALL_NOTE_FILES, CACHE_DIR, CACHE_TTL_SECONDS
from utils.github import GitHubFetchError, fetch_file


@dataclass
class LoadResult:
    filename: str
    text: str
    source: str
    fetched_at: float
    error: Optional[str] = None


def _cache_path(filename):
    safe = filename.replace("/", "__")
    return CACHE_DIR / safe


def _read_cache(filename):
    p = _cache_path(filename)
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    return text, p.stat().st_mtime


def _write_cache(filename, text):
    p = _cache_path(filename)
    try:
        p.write_text(text, encoding="utf-8")
    except OSError:
        pass


def load_file(filename, *, force_refresh=False):
    now = time.time()
    cache = _read_cache(filename)
    if not force_refresh and cache is not None:
        text, mtime = cache
        if now - mtime < CACHE_TTL_SECONDS:
            return LoadResult(filename=filename, text=text, source="cache", fetched_at=mtime)
    try:
        text = fetch_file(filename)
        _write_cache(filename, text)
        return LoadResult(filename=filename, text=text, source="github", fetched_at=now)
    except GitHubFetchError as exc:
        if cache is not None:
            text, mtime = cache
            return LoadResult(filename=filename, text=text, source="cache-stale",
                              fetched_at=mtime, error=str(exc))
        return LoadResult(filename=filename, text="", source="cache-stale",
                          fetched_at=0.0, error=str(exc))


def load_many(filenames, *, force_refresh=False):
    out = []
    for name in filenames:
        if not name:
            continue
        out.append(load_file(name, force_refresh=force_refresh))
    return out


def load_all_notes(*, force_refresh=False):
    return load_many(ALL_NOTE_FILES, force_refresh=force_refresh)
