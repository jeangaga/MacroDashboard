"""Search + filter layer over parsed Release objects."""
from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, Optional

import pandas as pd

from core.config import THEME_KEYWORDS, ALL_SCOPES
from core.parsers import Release
from utils.text import any_keyword, importance_rank


def releases_to_dataframe(releases):
    rows = []
    for r in releases:
        d = asdict(r)
        d["importance_rank"] = importance_rank(r.importance)
        d["countries_str"] = ", ".join(r.countries)
        d["themes_str"] = ", ".join(r.themes)
        rows.append(d)
    if not rows:
        return pd.DataFrame(columns=[
            "source_file", "block_stem", "region", "kind", "title",
            "importance", "importance_rank", "date_str", "countries_str",
            "themes_str", "raw_block",
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
    themes=None,
    countries=None,
    kinds=None,
    source_files=None,
):
    out = []
    q = (query or "").strip().lower()
    min_rank = importance_rank(min_importance) if min_importance else 0
    regions_set = {r for r in (regions or []) if r}
    themes_set = {t for t in (themes or [])}
    countries_set = {c for c in (countries or [])}
    kinds_set = {k for k in (kinds or [])}
    files_set = {f for f in (source_files or [])}

    for r in releases:
        if q and q not in (r.title + "\n" + r.raw_block).lower():
            continue
        if regions_set and r.region not in regions_set:
            continue
        if min_rank and importance_rank(r.importance) < min_rank:
            continue
        if themes_set and not (themes_set & set(r.themes)):
            continue
        if countries_set and not (countries_set & set(r.countries)):
            continue
        if kinds_set and r.kind not in kinds_set:
            continue
        if files_set and r.source_file not in files_set:
            continue
        out.append(r)

    out.sort(key=lambda r: (
        -importance_rank(r.importance),
        r.date_str or "",
        r.title.lower(),
    ))
    return out


def inflation_releases(releases):
    kws = THEME_KEYWORDS["Inflation"]
    out = [r for r in releases if any_keyword(r.title + "\n" + r.raw_block, kws)]
    out.sort(key=lambda r: (
        -importance_rank(r.importance),
        r.date_str or "",
        r.title.lower(),
    ))
    return out


def parse_command(cmd):
    """Translate QUICK-style shortcuts to filter kwargs.

    Examples:
      QUICK EUR            -> regions=[EUR], min_importance='***'
      QUICK2EUR            -> regions=[EUR], min_importance='****'
      QUICK2AUD            -> regions=[AUD], min_importance='****'
      CPI AUD              -> query='CPI', regions=[AUD]
      **** inflation EM    -> min_importance='****', themes=[Inflation], regions=[EM]
    """
    out = {}
    if not cmd:
        return out

    tokens = cmd.strip().split()
    remaining = []

    valid_scopes = set(ALL_SCOPES)
    theme_names = set(THEME_KEYWORDS.keys())

    if tokens:
        head = tokens[0].upper()
        if head.startswith("QUICK2") and head[6:] in valid_scopes:
            out["regions"] = [head[6:]]
            out["min_importance"] = "****"
            tokens = tokens[1:]
        elif head == "QUICK" and len(tokens) >= 2 and tokens[1].upper() in valid_scopes:
            out["regions"] = [tokens[1].upper()]
            out["min_importance"] = "***"
            tokens = tokens[2:]
        elif head == "QUICK":
            out["min_importance"] = "***"
            tokens = tokens[1:]

    for t in tokens:
        tu = t.upper()
        if tu in valid_scopes:
            out.setdefault("regions", []).append(tu)
            continue
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
