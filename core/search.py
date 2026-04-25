"""Search + filter layer over parsed Release objects."""
from __future__ import annotations

import datetime as _dt
from dataclasses import asdict
from typing import Iterable, Optional

import pandas as pd

from core.config import THEME_KEYWORDS, ALL_SCOPES, ALL_THEMES
from core.parsers import Release
from utils.text import (
    any_keyword,
    importance_rank,
    parse_release_date,
    release_type,
)


def releases_to_dataframe(releases):
    rows = []
    for r in releases:
        d = asdict(r)
        d["importance_rank"] = importance_rank(r.importance)
        d["countries_str"] = ", ".join(r.countries)
        d["themes_str"] = ", ".join(r.themes)
        d["release_type"] = release_type(r.title)
        rows.append(d)
    if not rows:
        return pd.DataFrame(columns=[
            "source_file", "block_stem", "region", "kind", "title",
            "importance", "importance_rank", "date_str", "countries_str",
            "themes_str", "release_type", "raw_block",
        ])
    df = pd.DataFrame(rows)
    return df.sort_values(
        by=["importance_rank", "date_str", "title"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def filter_releases(
    releases,
    *,
    query="",
    regions=None,
    min_importance=None,
    levels=None,
    themes=None,
    countries=None,
    kinds=None,
    source_files=None,
    release_types=None,
    since=None,
    until=None,
):
    """Filter a list of Release objects.

    levels: iterable of '*'/'**'/'***'/'****' to keep (any-of); overrides min_importance.
    release_types: iterable of canonical release names (output of release_type()).
    since/until: datetime.date inclusive bounds; releases without a parseable date
                 are dropped when either bound is set.
    """
    out = []
    q = (query or "").strip().lower()
    min_rank = importance_rank(min_importance) if min_importance else 0
    levels_set = {x for x in (levels or []) if x}
    regions_set = {r for r in (regions or []) if r}
    themes_set = {t for t in (themes or [])}
    countries_set = {c for c in (countries or [])}
    kinds_set = {k for k in (kinds or [])}
    files_set = {f for f in (source_files or [])}
    rtypes_set = {x for x in (release_types or []) if x}

    use_dates = since is not None or until is not None

    for r in releases:
        if q and q not in (r.title + "\n" + r.raw_block).lower():
            continue
        if regions_set and r.region not in regions_set:
            continue
        if levels_set:
            if r.importance not in levels_set:
                continue
        elif min_rank and importance_rank(r.importance) < min_rank:
            continue
        if themes_set and not (themes_set & set(r.themes)):
            continue
        if countries_set and not (countries_set & set(r.countries)):
            continue
        if kinds_set and r.kind not in kinds_set:
            continue
        if files_set and r.source_file not in files_set:
            continue
        if rtypes_set and release_type(r.title) not in rtypes_set:
            continue
        if use_dates:
            d = parse_release_date(r.date_str) or parse_release_date(r.raw_block)
            if d is None:
                continue
            if since and d < since:
                continue
            if until and d > until:
                continue
        out.append(r)

    out.sort(key=lambda r: (
        -importance_rank(r.importance),
        r.date_str or "",
        r.title.lower(),
    ))
    return out


def inflation_releases(releases):
    return theme_releases(releases, "Inflation")


def theme_releases(releases, theme):
    """Releases whose body or title contains any keyword for the given theme."""
    if theme not in THEME_KEYWORDS:
        return []
    kws = THEME_KEYWORDS[theme]
    out = [r for r in releases if any_keyword(r.title + "\n" + r.raw_block, kws)]
    out.sort(key=lambda r: (
        -importance_rank(r.importance),
        r.date_str or "",
        r.title.lower(),
    ))
    return out


def release_types_for(releases, scopes=None, countries=None):
    """Distinct canonical release names across a (filtered) set of releases."""
    scopes_set = {s for s in (scopes or []) if s}
    countries_set = {c for c in (countries or []) if c}
    out = set()
    for r in releases:
        if scopes_set and r.region not in scopes_set:
            continue
        if countries_set and not (countries_set & set(r.countries)):
            continue
        rt = release_type(r.title)
        if rt:
            out.add(rt)
    return sorted(out, key=str.lower)


def time_window_to_since(label, today=None):
    """Translate a UI label to a `since` datetime.date (or None for All)."""
    today = today or _dt.date.today()
    if not label or label == "All":
        return None
    if label == "Last 4 weeks":
        return today - _dt.timedelta(weeks=4)
    if label == "Last 3 months":
        # ~90 days; calendar-month math is overkill here
        return today - _dt.timedelta(days=92)
    if label == "Last 6 months":
        return today - _dt.timedelta(days=183)
    if label == "Last 12 months":
        return today - _dt.timedelta(days=365)
    if label == "YTD":
        return _dt.date(today.year, 1, 1)
    return None


_SCOPE_ALIASES = {
    "US": "USD", "USA": "USD", "AMERICA": "USD",
    "EU": "EUR", "EURO": "EUR", "EUROPE": "EUR", "EUROZONE": "EUR",
    "UK": "GBP", "BRITAIN": "GBP", "ENGLAND": "GBP",
    "JAPAN": "JPY",
    "CHINA": "CNH",
    "KOREA": "KRW", "SOUTHKOREA": "KRW", "S.KOREA": "KRW",
    "INDIA": "INR",
    "BRAZIL": "BRL",
    "MEXICO": "MXN",
    "SWEDEN": "SEK",
    "NORWAY": "NOK",
    "POLAND": "PLN",
    "TURKEY": "TRY",
    "TAIWAN": "TWD",
    "SOUTHAFRICA": "ZAR", "S.AFRICA": "ZAR", "SA": "ZAR",
    "SWITZERLAND": "CHF",
    "AUSTRALIA": "AUD",
    "CANADA": "CAD",
}


def _resolve_scope(token, valid_scopes):
    tu = token.upper()
    if tu in valid_scopes:
        return tu
    return _SCOPE_ALIASES.get(tu)


def parse_command(cmd):
    """Translate QUICK-style shortcuts to filter kwargs."""
    out = {}
    if not cmd:
        return out

    tokens = cmd.strip().split()
    remaining = []

    valid_scopes = set(ALL_SCOPES)
    theme_names = set(THEME_KEYWORDS.keys())

    if tokens:
        head = tokens[0].upper()
        if head.startswith("QUICK2"):
            resolved = _resolve_scope(head[6:], valid_scopes)
            if resolved:
                out["regions"] = [resolved]
                out["min_importance"] = "****"
                tokens = tokens[1:]
        elif head == "QUICK" and len(tokens) >= 2:
            resolved = _resolve_scope(tokens[1], valid_scopes)
            if resolved:
                out["regions"] = [resolved]
                out["min_importance"] = "***"
                tokens = tokens[2:]
            else:
                out["min_importance"] = "***"
                tokens = tokens[1:]
        elif head == "QUICK":
            out["min_importance"] = "***"
            tokens = tokens[1:]

    for t in tokens:
        resolved = _resolve_scope(t, valid_scopes)
        if resolved:
            regs = out.setdefault("regions", [])
            if resolved not in regs:
                regs.append(resolved)
            continue
        tu = t.upper()
        if tu in {"*", "**", "***", "****"}:
            if importance_rank(tu) > importance_rank(out.get("min_importance")):
                out["min_importance"] = tu
            continue
        theme_match = next((n for n in theme_names if n.lower() == t.lower()), None)
        if theme_match:
            out.setdefault("themes", []).append(theme_match)
            continue
        remaining.append(t)

    if remaining:
        out["query"] = " ".join(remaining)
    return out
