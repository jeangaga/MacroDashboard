"""Macro FX Feed Dashboard - Streamlit entry point."""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import streamlit as st

from core.config import (
    ALL_NOTE_FILES,
    ALL_SCOPES,
    ALL_THEMES,
    COUNTRY_SOURCE_PRIORITY,
    CURRENCY_SCOPES_DM,
    CURRENCY_SCOPES_EM,
    GITHUB_BRANCH,
    GITHUB_OWNER,
    GITHUB_REPO,
    PM_SCOPES,
    REGION_SCOPES,
    SCOPE_COUNTRIES,
    SCOPE_FILES,
    SCOPE_GROUP,
    country_source_status,
    default_catalogue_country,
    sources_for_country,
)
from core.loaders import LoadResult, load_file, load_many
from core.normalize import (
    catalogue_key,
    dedup_releases,
    normalize_release_name,
    release_key,
)
from core.parsers import (
    block_data_window,
    extract_blocks,
    extract_releases,
    releases_from_load_results,
)
from core.render import (
    importance_chip,
    render_block,
    render_load_status,
    render_release_card,
    render_release_list,
    source_badge,
)
from core.search import filter_releases
from utils.text import parse_release_date

st.set_page_config(
    page_title="Macro FX Feed Dashboard",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)

IMPORTANCE_LEVELS_UI = ["*", "**", "***", "****"]
TIME_WINDOWS = ["All", "Last 4 weeks", "Last 3 months", "Last 6 months", "Last 12 months", "YTD"]


@st.cache_data(ttl=300, show_spinner=False)
def _cached_load_file(filename, version):
    return load_file(filename)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_load_many(filenames, version):
    return load_many(list(filenames))


def _refresh_token():
    return st.session_state.get("refresh_token", 0)


def _load_file(filename):
    return _cached_load_file(filename, _refresh_token())


def _load_many(filenames):
    return _cached_load_many(tuple(filenames), _refresh_token())


def _scope_label(scope):
    return f"{scope}  -  {SCOPE_GROUP.get(scope, '-')}"


def _available_views(scope):
    views = SCOPE_FILES.get(scope, {})
    order = ["frozen_week", "live_week", "pm_style", "macro_note"]
    return [(k, views.get(k, "")) for k in order if views.get(k)]


def _view_display(view_key):
    return {
        "frozen_week": "Frozen week",
        "live_week":   "Live week",
        "pm_style":    "PM style",
        "macro_note":  "Macro note",
    }.get(view_key, view_key)


def sidebar():
    st.sidebar.title("Macro FX Feed")
    st.sidebar.caption(f"Source: `{GITHUB_OWNER}/{GITHUB_REPO}` @ `{GITHUB_BRANCH}`")

    st.sidebar.subheader("Scope")
    group = st.sidebar.radio(
        "Group",
        options=["Region", "DM currency", "EM currency", "PM / shared"],
        index=0, horizontal=True, label_visibility="collapsed",
        key="sb_group",
    )
    group_options = {
        "Region":       REGION_SCOPES,
        "DM currency":  CURRENCY_SCOPES_DM,
        "EM currency":  CURRENCY_SCOPES_EM,
        "PM / shared":  PM_SCOPES,
    }[group]
    scope = st.sidebar.selectbox(
        "Scope", options=group_options, index=0, label_visibility="collapsed",
        key="sb_scope",
    )

    st.sidebar.subheader("View")
    views = _available_views(scope)
    if views:
        view_labels = [_view_display(k) for k, _ in views]
        view_idx = st.sidebar.radio(
            "View", options=list(range(len(views))),
            format_func=lambda i: view_labels[i],
            label_visibility="collapsed",
            key="sb_view",
        )
        view = views[view_idx][0]
    else:
        view = "frozen_week"
        st.sidebar.caption("No views available for this scope.")

    st.sidebar.subheader("Importance")
    levels = st.sidebar.multiselect(
        "Importance levels",
        options=IMPORTANCE_LEVELS_UI,
        default=["***", "****"],
        label_visibility="collapsed",
        key="sb_levels",
        help="Pick any combination of importance levels (* through ****).",
    )

    st.sidebar.subheader("Time window")
    time_window = st.sidebar.selectbox(
        "Time window",
        options=TIME_WINDOWS, index=0, label_visibility="collapsed",
        key="sb_time_window",
        help="Filter results to this window.",
    )

    st.sidebar.divider()
    if st.sidebar.button("Refresh from GitHub", use_container_width=True, key="sb_refresh"):
        st.session_state["refresh_token"] = _refresh_token() + 1
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption(f"Cache token: {_refresh_token()}")

    return {
        "scope": scope,
        "view": view,
        "levels": levels,
        "time_window": time_window,
    }


def tab_weekly_monitor(state):
    scope = state["scope"]
    view = state["view"]
    levels = state["levels"]
    scope_file = SCOPE_FILES.get(scope, {}).get(view, "")

    header_cols = st.columns([3, 2])
    header_cols[0].header(f"{scope} - {_view_display(view)}")
    if levels:
        header_cols[1].caption("Importance: " + " ".join(levels))

    if not scope_file:
        st.warning(f"No `{_view_display(view)}` file configured for `{scope}`.")
        return

    result = _load_file(scope_file)
    if result.error:
        st.warning(result.error)
    if not result.text:
        st.info(f"No content available for `{scope_file}`.")
        return

    blocks = extract_blocks(result.text, source_file=result.filename)
    scope_blocks = [b for b in blocks if b.region == scope] or blocks
    if not scope_blocks:
        st.info(f"No `{scope}` blocks parsed from `{scope_file}`.")
        return

    # File / region heading once, with source + timestamp.
    st.caption(
        f"File: `{scope_file}`  |  Region: `{scope}`  |  {source_badge(result)}"
    )

    # Build (label, block, start, end) entries so the Week selector can rank
    # by date even when only an inferred range is available.
    entries = []
    for b in scope_blocks:
        label, start, end = block_data_window(b)
        entries.append({"label": label, "block": b, "start": start, "end": end})

    # Sort weekly entries with most recent first. Blocks without any date
    # information sink to the bottom in stable order.
    entries.sort(
        key=lambda e: (e["start"] or _dt.date.min),
        reverse=True,
    )

    # Week selector if there is more than one weekly entry.
    if len(entries) > 1:
        options = ["All weeks"] + [
            (e["label"] or f"{e['block'].stem} (no window)")
            for e in entries
        ]
        choice = st.selectbox(
            "Week",
            options=list(range(len(options))),
            format_func=lambda i: options[i],
            index=0,  # default = "All weeks"
            key=f"wm_week_{scope}_{view}",
        )
        if choice == 0:
            selected_entries = entries
        else:
            selected_entries = [entries[choice - 1]]
    else:
        selected_entries = entries

    sort_desc = st.checkbox(
        "Sort releases newest-first",
        value=False,
        key=f"wm_sort_{scope}_{view}",
        help="Off = chronological order (Mon to Fri). On = newest first.",
    )

    min_importance = min(levels, key=len) if levels else None

    for entry in selected_entries:
        b = entry["block"]
        label = entry["label"]
        if label:
            st.markdown(f"### Data window: {label}")
        else:
            st.markdown(f"### {b.stem} (no data window declared)")

        releases = extract_releases(b)
        # Dedup by stable key (country|normalized|date|importance) so the
        # same Reuters event parsed twice in the same archive doesn't
        # surface twice.
        releases = dedup_releases(releases)
        if min_importance:
            releases = filter_releases(releases, min_importance=min_importance)

        if not releases:
            st.info("No releases at the selected importance in this week.")
            continue

        # Stable sort: by parsed date (asc by default), preserving original
        # order on ties (which mirrors how the source file is laid out).
        def _sort_key(idx_r):
            idx, r = idx_r
            d = parse_release_date(r.date_str) or _dt.date.min
            return (d, idx)

        indexed = list(enumerate(releases))
        indexed.sort(key=_sort_key, reverse=sort_desc)
        sorted_releases = [r for _, r in indexed]

        st.caption(f"{len(sorted_releases)} release(s) in this window")
        for r in sorted_releases:
            render_release_card(r, default_expanded=False)


_MACRO_NOTE_VIEWS = ["Latest note only", "Previous notes", "All notes archive"]


def _macro_note_versions(blocks):
    """Order parsed note blocks (already split by Data window) so the most
    recent version is first.

    Sort key: end-date desc, start-date desc, then stable order. Blocks with
    no detectable window sink to the bottom but keep their original order.
    """
    annotated = []
    for i, b in enumerate(blocks):
        label, start, end = block_data_window(b)
        annotated.append((b, label, start, end, i))
    annotated.sort(
        key=lambda x: (
            x[3] or _dt.date.min,  # end-date desc primary
            x[2] or _dt.date.min,  # start-date desc tiebreak
            -x[4],                 # later original index wins ties (stable-ish)
        ),
        reverse=True,
    )
    return annotated


def tab_macro_notes(state):
    st.header("Macro Notes")
    note_options = [
        (scope, SCOPE_FILES[scope]["macro_note"])
        for scope in ALL_SCOPES
        if SCOPE_FILES[scope].get("macro_note")
    ]
    if not note_options:
        st.info("No macro note files configured.")
        return

    # Scope-aware default: pre-select the macro note tied to the sidebar
    # scope (e.g. sidebar=USD -> USD_MACRO_NOTE.txt).
    sidebar_scope = (state or {}).get("scope", "")
    default_idx = 0
    for i, (s, _) in enumerate(note_options):
        if s == sidebar_scope:
            default_idx = i
            break

    cols = st.columns([3, 2])
    labels = [f"{s}  -  {fn}" for s, fn in note_options]
    idx = cols[0].selectbox(
        "Macro note file",
        options=list(range(len(note_options))),
        index=default_idx,
        format_func=lambda i: labels[i],
        key="mn_select",
        help="Default tracks the sidebar scope. Pick another to view it.",
    )
    view_mode = cols[1].selectbox(
        "View",
        options=_MACRO_NOTE_VIEWS,
        index=0,
        key="mn_view_mode",
        help="Latest = most recent note version only. "
             "Previous = older versions as collapsed cards. "
             "Archive = latest + all previous, all collapsed.",
    )

    scope, filename = note_options[idx]
    result = _load_file(filename)
    if result.error:
        st.warning(result.error)
    if not result.text:
        st.info(f"No content available for `{filename}`.")
        return

    # extract_blocks(split_weekly=True) already splits each marker block by
    # any embedded "Data window:" line, which is exactly the version unit
    # we want here. Each annotated tuple is (block, label, start, end, idx).
    blocks = extract_blocks(result.text, source_file=result.filename)
    versions = _macro_note_versions(blocks)
    if not versions:
        st.info(f"No note versions parsed from `{filename}`.")
        return

    latest_block, latest_label, latest_start, latest_end, _ = versions[0]
    previous = versions[1:]

    # File / scope / latest window header - shown ONCE at the top, never
    # repeated before each historical block.
    header_bits = [f"File: `{filename}`", f"Scope: `{scope}`",
                   source_badge(result)]
    if latest_label:
        header_bits.append(f"Latest data window: {latest_label}")
    elif latest_end:
        header_bits.append(f"Latest as-of: {latest_end.isoformat()}")
    st.caption("  |  ".join(header_bits))

    if view_mode == "Latest note only":
        st.markdown(f"### {scope} - Macro Note")
        meta_bits = []
        if latest_label:
            meta_bits.append(f"Data window: {latest_label}")
        n_lines = len(latest_block.raw_text.splitlines())
        n_chars = len(latest_block.raw_text)
        meta_bits.append(f"{n_lines:,} lines  -  {n_chars:,} chars")
        st.caption("  |  ".join(meta_bits))
        # Download button: lets the user grab the full block as plain text,
        # which is the most reliable proof that the parser captured every
        # line. Place it right next to the metadata so it's obviously about
        # the block currently rendered.
        st.download_button(
            "Download full note (.txt)",
            data=latest_block.raw_text,
            file_name=f"{scope}_{filename}".replace(".txt", "") + "_latest.txt",
            mime="text/plain",
            key="mn_latest_download",
        )
        # Bound the height so the user has a per-block scroll surface --
        # otherwise a 700-line note pushes everything else off the page and
        # it can look like the rendering is truncated.
        with st.container(height=600, border=True):
            st.code(latest_block.raw_text, language="text", wrap_lines=True)
        if previous:
            st.caption(
                f"{len(previous)} earlier version(s) hidden. "
                "Switch View to 'Previous notes' or 'All notes archive' to see them."
            )
        return

    if view_mode == "Previous notes":
        if not previous:
            st.info("No previous note versions in this file.")
            return
        st.caption(f"{len(previous)} previous version(s).")
        for blk, lbl, s, e, _ in previous:
            label = lbl or (e.isoformat() if e else f"{blk.stem} (no window)")
            with st.expander(f"Data window: {label}", expanded=False):
                st.code(blk.raw_text, language="text", wrap_lines=True)
        return

    # Archive mode: latest + all previous, all collapsed in one timeline.
    st.caption(f"{len(versions)} note version(s) in archive.")
    for j, (blk, lbl, s, e, _) in enumerate(versions):
        label = lbl or (e.isoformat() if e else f"{blk.stem} (no window)")
        prefix = "Latest" if j == 0 else "Previous"
        with st.expander(f"{prefix}  -  Data window: {label}", expanded=False):
            st.code(blk.raw_text, language="text", wrap_lines=True)


_CONFIDENCE_ICON = {"High": "H", "Medium": "M", "Low": "L"}
_CATALOGUE_THEMES = ["Inflation", "Labor", "Growth", "Policy", "External", "Housing"]


def _release_sort_key(r):
    d = parse_release_date(r.date_str) or parse_release_date(r.raw_block)
    return d or _dt.date.min


def _catalogue_sort_key(r):
    """Catalogue chronology sorts by reference period (what the release
    describes), with the publication date as a tiebreak.

    Period-less releases sink to the bottom so a delayed publication for
    Mar can never outrank a fresh print for Apr. The publication date is
    used only to break ties between releases for the same period (e.g.
    a frozen vs live read of the same Mar CPI).
    """
    period = getattr(r, "reference_period", None) or ""
    pub = parse_release_date(r.date_str) or _dt.date.min
    return (period, pub)


_EXPORT_SEPARATOR = "-" * 50


def format_release_export(country, release_name, releases, *, limit=None):
    """Build a plain-text export of `releases` for the given catalogue row.

    Designed for paste into an LLM:
      - no markdown / no formatting
      - one block per occurrence with `date | importance` + title + full
        raw_block, separated by a 50-dash divider
      - caller is responsible for sorting (latest reference period first)

    `limit` truncates to the first N occurrences. None = all.
    """
    rels_all = list(releases or [])
    rels = rels_all[:limit] if (limit and limit < len(rels_all)) else rels_all

    header = f"{country} - {release_name}"
    parts = [header, ""]
    if not rels:
        parts.append("(no occurrences)")
        return "\n".join(parts) + "\n"

    if limit and limit < len(rels_all):
        parts.append(f"Latest {len(rels)} of {len(rels_all)} occurrences")
    else:
        parts.append(f"All {len(rels)} occurrences")
    parts.append("")

    for i, r in enumerate(rels):
        date = (getattr(r, "date_str", None) or "no date").strip()
        imp = getattr(r, "importance", None) or "?"
        title = getattr(r, "title", "") or ""
        raw = (getattr(r, "raw_block", "") or "").rstrip("\n")
        period = getattr(r, "reference_period", None)
        head_bits = [f"{date} | {imp}"]
        if period:
            head_bits.append(f"period {period}")
        parts.append(" | ".join(head_bits))
        parts.append(title)
        parts.append("")
        parts.append(raw)
        if i < len(rels) - 1:
            parts.append("")
            parts.append(_EXPORT_SEPARATOR)
            parts.append("")
    return "\n".join(parts) + "\n"


def _export_filename(country, release_name):
    safe = f"{country}_{release_name}".replace("/", "-").replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c in "-_.")
    return f"{safe or 'export'}.txt"


def _catalogue_dedup(releases):
    """Drop duplicates by catalogue_key, keeping the FIRST occurrence.

    Caller must order `releases` so the preferred occurrence comes first
    (e.g. frozen before live -- the catalogue does this by ordering
    `allowed_files` frozen-first). Releases whose `catalogue_key` is empty
    (no reference_period) are kept as-is so we never collapse two unrelated
    releases just because their period couldn't be inferred.
    """
    seen = set()
    out = []
    for r in releases or []:
        k = catalogue_key(r)
        if k:
            if k in seen:
                continue
            seen.add(k)
        out.append(r)
    return out


def tab_country_release_catalogue():
    """Per-country index of recurring releases. Click a row to see latest +
    previous occurrences, with optional latest-vs-previous compare."""
    st.header("Country Release Catalogue")
    st.caption(
        "For each country, list every recurring macro release in the archive. "
        "Click a row to open the latest occurrence and compare with previous prints."
    )

    # Load only the country-priority files later, but we still need an
    # initial pass to know which countries appear in the archive at all.
    # We use the union of every country's frozen+live source set so the
    # selectbox lists exactly the countries we have data for.
    catalogue_countries = list(COUNTRY_SOURCE_PRIORITY.keys())
    if not catalogue_countries:
        st.info("No countries are mapped to source files. See COUNTRY_SOURCE_PRIORITY.")
        return

    cols = st.columns([2, 2, 3])
    country = cols[0].selectbox(
        "Country",
        options=sorted(catalogue_countries),
        key="cc_country",
        help="Catalogue is built only from this country's dedicated source files.",
    )
    theme_filter = cols[1].multiselect(
        "Theme", options=_CATALOGUE_THEMES, default=[], key="cc_themes",
        help="Filter the catalogue to one or more themes.",
    )
    name_query = cols[2].text_input(
        "Search release name", value="",
        placeholder="cpi | labour | retail | central bank",
        key="cc_search",
    )

    cols_opts = st.columns([2, 2, 2])
    include_live = cols_opts[0].checkbox(
        "Include current live week",
        value=False,
        key="cc_include_live",
        help="Default = frozen archive only. Toggle to add *_WEEK_LIVE_MACRO.txt "
             "(provisional, current week). Frozen takes precedence on duplicates.",
    )
    only_known = cols_opts[1].checkbox(
        "Hide unknown / low-confidence rows",
        value=True,
        key="cc_only_known",
        help="On (default): only show releases that map to a known recurring "
             "indicator. Off: also show low-confidence titles.",
    )

    # Resolve the country -> file allow-list for this view.
    allowed_files = sources_for_country(country, include_live=include_live)
    if not allowed_files:
        st.info(f"No source files mapped for `{country}`. Add an entry to COUNTRY_SOURCE_PRIORITY.")
        return

    # Sources used label: split frozen vs live for visual clarity.
    frozen_used = [f for f in allowed_files if country_source_status(f) == "frozen"]
    live_used   = [f for f in allowed_files if country_source_status(f) == "live"]
    src_caption_bits = []
    if frozen_used:
        src_caption_bits.append("Frozen: " + ", ".join(f"`{f}`" for f in frozen_used))
    if live_used:
        src_caption_bits.append("Live: " + ", ".join(f"`{f}`" for f in live_used))
    st.caption("Sources used  |  " + "  |  ".join(src_caption_bits))

    # Load only the files in the allow-list. Restrict releases to (a) the
    # selected country AND (b) source_file in the allow-list.
    all_results = _load_many(allowed_files)
    render_load_status(all_results)
    all_releases = releases_from_load_results(all_results)
    if not all_releases:
        st.info(f"No releases parsed from {', '.join(allowed_files)}.")
        return

    country_releases = [
        r for r in all_releases
        if country in (r.countries or []) and r.source_file in allowed_files
    ]
    if not country_releases:
        st.info(f"No releases tagged with {country} in the allowed source files.")
        return

    # Catalogue dedup uses (country, normalized_name, reference_period) so
    # two parses of the same Mar CPI (frozen + live, possibly with different
    # importance flags) collapse into one occurrence. Frozen wins because
    # frozen files come first in `allowed_files` and _catalogue_dedup keeps
    # the FIRST occurrence. Releases with no reference_period are kept
    # un-collapsed (we never merge unrelated releases just because the
    # period couldn't be inferred from the title).
    country_releases = _catalogue_dedup(country_releases)

    groups = {}
    meta = {}
    for r in country_releases:
        name, theme, conf = normalize_release_name(r.title)
        if not name:
            continue
        if only_known and conf == "Low":
            continue
        if theme_filter and theme not in theme_filter:
            continue
        groups.setdefault(name, []).append(r)
        if name not in meta:
            meta[name] = (theme, conf)

    if not groups:
        st.info("No recurring releases match these filters.")
        return

    rows = []
    for name, rels in groups.items():
        # Sort by reference period (what the release describes), with the
        # publication date as a tiebreak. The row's "latest" is therefore
        # the freshest reference period available, not whichever block was
        # published last.
        rels_sorted = sorted(rels, key=_catalogue_sort_key, reverse=True)
        latest = rels_sorted[0]
        regions = sorted({(r.region or "-") for r in rels})
        files = sorted({r.source_file for r in rels})
        theme, conf = meta[name]
        rows.append({
            "Release": name,
            "Theme": theme or "-",
            "Conf": _CONFIDENCE_ICON.get(conf, conf),
            "Occurrences": len(rels),
            "Latest period": latest.reference_period or "-",
            "Latest date": latest.date_str or "-",
            "Imp": latest.importance or "-",
            "Regions": ", ".join(regions),
            "Files": ", ".join(files),
        })
    rows.sort(key=lambda x: (-x["Occurrences"], x["Release"].lower()))

    df = pd.DataFrame(rows)
    st.caption(f"{len(rows)} recurring release(s) for {country}.")
    selection = st.dataframe(
        df,
        use_container_width=True,
        height=min(420, 60 + 36 * max(len(rows), 1)),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="cc_table",
    )

    selected_idx = []
    sel = getattr(selection, "selection", None)
    if sel is not None:
        selected_idx = list(getattr(sel, "rows", []) or [])

    if not selected_idx:
        st.caption("Select a row above to see latest + previous occurrences.")
        return

    selected_name = rows[selected_idx[0]]["Release"]
    # Same chronology rule as the table: latest reference period first, with
    # publication date as the tiebreak.
    rels = sorted(groups[selected_name], key=_catalogue_sort_key, reverse=True)

    st.divider()
    theme, conf = meta[selected_name]
    st.subheader(f"{country}  -  {selected_name}")
    st.caption(
        f"Theme: `{theme or '-'}`  |  Confidence: `{conf}`  |  "
        f"Occurrences in archive: `{len(rels)}`"
    )

    # Export panel: latest N occurrences as one LLM-ready text blob.
    exp_cols = st.columns([1, 1, 2])
    limit_options = [3, 4, 6, "All"]
    limit_choice = exp_cols[0].selectbox(
        "Export count",
        options=limit_options,
        index=1,  # default = 4
        key="cc_export_limit",
        help="Number of latest occurrences (sorted by reference period) "
             "to include in the export.",
    )
    limit = None if limit_choice == "All" else int(limit_choice)
    export_text = format_release_export(country, selected_name, rels, limit=limit)
    exp_cols[1].download_button(
        "Download .txt",
        data=export_text,
        file_name=_export_filename(country, selected_name),
        mime="text/plain",
        key="cc_export_download",
        use_container_width=True,
    )
    with st.expander("Show export text (click to copy)", expanded=False):
        st.code(export_text, language="text", wrap_lines=True)

    compare = st.checkbox(
        "Compare latest vs previous side-by-side",
        value=False, key="cc_compare",
        disabled=(len(rels) < 2),
        help="Disabled when only one occurrence is available.",
    )

    if compare and len(rels) >= 2:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Latest**  -  {rels[0].date_str or 'no date'}  -  `{rels[0].importance or '?'}`")
            st.caption(f"Original title: {rels[0].title}  |  File: `{rels[0].source_file}`")
            if rels[0].raw_block:
                st.code(rels[0].raw_block, language="text", wrap_lines=True)
            else:
                st.warning("raw block unavailable")
        with c2:
            st.markdown(f"**Previous**  -  {rels[1].date_str or 'no date'}  -  `{rels[1].importance or '?'}`")
            st.caption(f"Original title: {rels[1].title}  |  File: `{rels[1].source_file}`")
            if rels[1].raw_block:
                st.code(rels[1].raw_block, language="text", wrap_lines=True)
            else:
                st.warning("raw block unavailable")
        if len(rels) > 2:
            st.markdown(f"**Earlier occurrences** ({len(rels) - 2})")
            for r in rels[2:]:
                label = f"{r.date_str or 'no date'}  |  {r.importance or '?'}  |  {r.title}"
                with st.expander(label, expanded=False):
                    st.caption(f"File: `{r.source_file}`  |  Scope: `{r.region or '-'}`")
                    if r.raw_block:
                        st.code(r.raw_block, language="text", wrap_lines=True)
                    else:
                        st.warning("raw block unavailable")
        return

    # Default layout: latest is a collapsed expander, identical format to previous
    latest = rels[0]
    st.markdown("**Latest occurrence**")
    latest_label = f"{latest.date_str or 'no date'}  |  {latest.importance or '?'}  |  {latest.title}"
    with st.expander(latest_label, expanded=False):
        st.caption(f"File: `{latest.source_file}`  |  Scope: `{latest.region or '-'}`")
        if latest.raw_block:
            st.code(latest.raw_block, language="text", wrap_lines=True)
        else:
            st.warning("raw block unavailable")

    if len(rels) > 1:
        st.markdown(f"**Previous occurrences** ({len(rels) - 1})")
        for r in rels[1:]:
            label = f"{r.date_str or 'no date'}  |  {r.importance or '?'}  |  {r.title}"
            with st.expander(label, expanded=False):
                st.caption(f"File: `{r.source_file}`  |  Scope: `{r.region or '-'}`")
                if r.raw_block:
                    st.code(r.raw_block, language="text", wrap_lines=True)
                else:
                    st.warning("raw block unavailable")
    else:
        st.caption("No previous occurrences in archive.")


# ---------------------------------------------------------------------------
# Scope as a global state driver
# ---------------------------------------------------------------------------
# Sidebar scope (sb_scope) is the source of truth. Every tab keeps its own
# widget state (file selection, country selection, search, levels, themes,
# weeks). When scope changes, those persisted selections must be cleared so
# each tab re-derives its defaults from the new scope.

# Tab-local widget keys to drop on scope change. The sidebar keys
# (sb_group, sb_scope, sb_view, sb_levels, sb_themes, sb_time_window) and
# the refresh token are deliberately NOT listed here.
_SCOPE_RESET_KEYS = (
    # Macro Notes
    "mn_select", "mn_view_mode",
    # Country Release Catalogue
    "cc_country", "cc_themes", "cc_search", "cc_include_live",
    "cc_only_known", "cc_table", "cc_compare",
    "cc_export_limit",
)


def _reset_state_for_scope(new_scope, session=None):
    """Pop tab-local widget keys and seed scope-driven defaults.

    Pulled out as a pure function (with `session` injectable) so it is
    unit-testable without spinning up Streamlit. Returns the same session
    dict for chaining.
    """
    if session is None:
        session = st.session_state
    for key in _SCOPE_RESET_KEYS:
        try:
            del session[key]
        except KeyError:
            pass
    # Pre-seed the catalogue country so the new tab default reflects scope.
    new_country = default_catalogue_country(new_scope)
    if new_country:
        session["cc_country"] = new_country
    session["_prev_scope"] = new_scope
    return session


def _handle_scope_change(scope):
    """If sidebar scope changed since the last render, reset tab state and rerun.

    First render: just records the scope, no reset (so users keep any
    selections they made before the very first widget refresh). Subsequent
    renders: on real change, reset and rerun so widgets pick up new defaults.
    Returns True when a reset happened.
    """
    prev = st.session_state.get("_prev_scope")
    if prev is None:
        # First render: don't reset tab state (user may have just typed a
        # query or selected a row), but DO seed the catalogue country so
        # the Catalogue tab opens on the sidebar scope's representative
        # country (USD -> US, EUR -> Eurozone, GBP -> UK ...) rather than
        # falling back to the alphabetical-first option.
        if "cc_country" not in st.session_state:
            seeded = default_catalogue_country(scope)
            if seeded:
                st.session_state["cc_country"] = seeded
        st.session_state["_prev_scope"] = scope
        return False
    if prev == scope:
        return False
    _reset_state_for_scope(scope)
    st.rerun()
    return True


def main():
    state = sidebar()
    # Scope is global. The moment it changes, every tab forgets its prior
    # widget state and re-derives defaults from the new scope.
    _handle_scope_change(state["scope"])

    st.title("Macro FX Feed Dashboard")
    st.caption(
        "Structured macro terminal over the GitHub-hosted archive. "
        "Sidebar scopes the view across all tabs."
    )
    st.caption(f"Current scope: `{state['scope']}`")

    tab1, tab2, tab3 = st.tabs([
        "Weekly Monitor", "Macro Notes", "Country Release Catalogue",
    ])
    with tab1:
        tab_weekly_monitor(state)
    with tab2:
        tab_macro_notes(state)
    with tab3:
        tab_country_release_catalogue()


if __name__ == "__main__":
    main()
