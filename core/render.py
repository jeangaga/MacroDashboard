"""Streamlit render helpers."""
from __future__ import annotations

import time
from typing import Iterable, Optional

import streamlit as st

from core.config import IMPORTANCE_LABELS
from core.loaders import LoadResult
from core.parsers import Block, Release
from utils.text import collapse_blank_lines, importance_rank


def source_badge(result):
    when = time.strftime("%H:%M:%S", time.localtime(result.fetched_at)) if result.fetched_at else "-"
    if result.source == "github":
        return f"GitHub  fetched {when}"
    if result.source == "cache":
        return f"local cache  {when}"
    if result.source == "cache-stale":
        suffix = f"  last fetched {when}" if result.fetched_at else ""
        return f"stale cache (GitHub unreachable){suffix}"
    return result.source


def importance_chip(flag):
    if not flag:
        return "-"
    label = IMPORTANCE_LABELS.get(flag, flag)
    return f"{flag} ({label})"


def render_block(block, *, min_importance=None, levels=None):
    """Render a parsed block. If `levels` (list of '*'..'****') or `min_importance`
    is provided, filter the contained releases. Always renders compact cards
    that are collapsed by default.
    """
    header = f"**{block.stem}**  {block.source_file}"
    if block.region:
        header += f"  region: `{block.region}`"
    st.markdown(header)

    if not levels and not min_importance:
        st.code(collapse_blank_lines(block.raw_text), language="text", wrap_lines=True)
        return

    from core.parsers import extract_releases
    from core.search import filter_releases

    releases = extract_releases(block)
    releases = filter_releases(releases, levels=levels, min_importance=min_importance)
    if not releases:
        label = "/".join(levels) if levels else f">= {min_importance}"
        st.info(f"No releases at importance {label} in this block.")
        return
    label = "/".join(levels) if levels else f">= {min_importance}"
    st.caption(f"{len(releases)} release(s) at importance {label}")
    for r in releases:
        render_release_card(r)


def render_release_card(release, *, default_expanded=False):
    """Compact, collapsed-by-default release card.

    Header: title  ·  ****  ·  date  ·  country (if any)
    Body (when expanded): scope/file/themes meta + the full raw block.
    """
    # Header format: "[date] | [importance] | [country] - [title]"
    date_part = release.date_str or "no date"
    imp_part = release.importance or "?"
    country_part = ", ".join(release.countries) if release.countries else ""
    title_part = release.title or "(untitled release)"
    if country_part and country_part.lower() not in title_part.lower():
        tail = f"{country_part} - {title_part}"
    else:
        tail = title_part
    label = f"{date_part}  |  {imp_part}  |  {tail}"

    with st.expander(label, expanded=default_expanded):
        meta_cols = st.columns(3)
        meta_cols[0].caption(f"Scope: `{release.region or '-'}`")
        meta_cols[1].caption(f"File: `{release.source_file}`")
        meta_cols[2].caption(
            "Themes: " + (", ".join(release.themes) if release.themes else "-")
        )
        st.code(release.raw_block, language="text", wrap_lines=True)


def render_release_list(releases, *, empty_message="No matching releases.", limit=None):
    releases = list(releases)
    if not releases:
        st.info(empty_message)
        return
    total = len(releases)
    if limit is not None and total > limit:
        st.caption(f"Showing first {limit} of {total} result(s).")
        releases = releases[:limit]
    else:
        st.caption(f"{total} result(s).")
    for r in releases:
        render_release_card(r, default_expanded=False)


def render_load_status(results):
    results = list(results)
    if not results:
        return
    ok = sum(1 for r in results if r.text and not r.error)
    stale = sum(1 for r in results if r.source == "cache-stale" and r.text)
    missing = sum(1 for r in results if not r.text)
    bits = [f"{ok} loaded"]
    if stale:
        bits.append(f"{stale} from stale cache")
    if missing:
        bits.append(f"{missing} missing")
    st.caption("  ".join(bits))
