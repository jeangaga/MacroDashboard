"""Macro FX Feed Dashboard - Streamlit entry point."""
from __future__ import annotations

import datetime as _dt
import re

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
    NARRATIVE_SECTION_IDS,
    block_data_window,
    extract_blocks,
    extract_central_bank_tape_text,
    extract_macro_note_versions,
    extract_macro_synthesis,
    extract_releases,
    extract_week_sections,
    filter_subsections,
    has_week_section,
    releases_from_load_results,
    split_top_level_sections,
    subsection_titles,
    week_section_text,
)
from core.render import (
    importance_chip,
    render_block,
    render_central_bank_tape,
    render_load_status,
    render_release_card,
    render_release_list,
    render_week_note_sections,
    render_week_summary,
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


# --- Week Recap tab ---------------------------------------------------------
#
# The landing tile: section I (COMPRESSED WEEK NOTE) of the most recent weeks,
# stacked newest-first so you read back through time by scrolling down. Two
# weeks by default -- the comparison the note is usually read for.
_RECAP_WEEK_OPTIONS = [1, 2, 3, 4, 6, 8]
_RECAP_DEFAULT_WEEKS = 2


# A standalone run of 2-4 asterisks: an importance flag ("**** US - CPI"), not
# markdown emphasis. Must be whitespace-delimited on both sides, which is what
# separates it from a `**bold**` pair or a `* ` bullet.
_IMPORTANCE_FLAG_RE = re.compile(r"(?<!\S)(\*{2,4})(?!\S)")


def _escape_importance_flags(text):
    """Escape bare importance flags so markdown renders them literally.

    Compressed notes are markdown: ~28 bullets and ~28 bold pairs each, which
    is unreadable as preformatted text. But they also carry bare importance
    flags, and `* **** **Employment Situation**` hands markdown an unmatched
    emphasis run that swallows the flag. Escaping just the standalone runs
    keeps `****` visible while leaving real `**bold**` and `* ` bullets alone.

    Content is unchanged -- this only escapes markup so the stored text renders
    as written.
    """
    if not text:
        return text
    return _IMPORTANCE_FLAG_RE.sub(
        lambda m: "\\" + "\\".join(m.group(1)), text
    )


def _recap_entries(blocks):
    """Weekly blocks paired with their compressed note, most recent first.

    Sorted by data-window end then start, both descending. Blocks with no
    window sink to the bottom in stable document order. `body` is the section
    I text, or "" for a week that predates the A-I format.
    """
    entries = []
    for i, b in enumerate(blocks or []):
        label, start, end = block_data_window(b)
        entries.append({
            "block": b,
            "label": label,
            "start": start,
            "end": end,
            "body": week_section_text(b, "compressed"),
            "idx": i,
        })
    entries.sort(
        key=lambda e: (e["end"] or _dt.date.min,
                       e["start"] or _dt.date.min,
                       -e["idx"]),
        reverse=True,
    )
    return entries


def _recap_week_choices(available):
    """Week-count options for the picker, capped at what the file actually has."""
    choices = [n for n in _RECAP_WEEK_OPTIONS if n <= available]
    if available and available not in choices:
        choices.append(available)
    return sorted(set(choices))


def _recap_subsection_titles(entries):
    """Every `###` subsection title across the shown weeks, in document order.

    Newest week first, so its running order sets the option order; titles a
    newer note dropped still appear, appended where an older week has them.
    """
    seen = []
    for entry in entries or []:
        for title in subsection_titles(entry.get("body") or ""):
            if title not in seen:
                seen.append(title)
    return seen


def _seed_recap_sections(session_state, key, options):
    """Default the subsection picker to everything, and keep it valid.

    First render selects all. On later renders the stored selection is pruned
    to options that still exist (weeks change, and a note may drop a
    subsection), because streamlit rejects a default holding values that are
    no longer in `options`. A selection pruned to nothing falls back to all,
    so the tab can't get stuck showing an empty note.
    """
    if key not in session_state:
        session_state[key] = list(options)
        return session_state[key]
    kept = [t for t in session_state[key] if t in options]
    session_state[key] = kept if kept else list(options)
    return session_state[key]


def tab_week_recap(state):
    """WEEK RECAP: the compressed note (I) for the last N weeks, newest first."""
    scope = state["scope"]

    # Always the scope's canonical frozen WEEK file -- the recap is about the
    # week object itself, so it doesn't follow the sidebar's view selector
    # (which can point at a macro note or PM file that has no section I).
    scope_file = SCOPE_FILES.get(scope, {}).get("frozen_week", "")

    st.header(f"{scope} - Week Recap")
    if not scope_file:
        st.warning(f"No weekly file configured for `{scope}`.")
        return

    result = _load_file(scope_file)
    if result.error:
        st.warning(result.error)
    if not result.text:
        st.info(f"No content available for `{scope_file}`.")
        return

    blocks = extract_blocks(result.text, source_file=result.filename)
    scope_blocks = [b for b in blocks if b.region == scope] or blocks
    entries = _recap_entries(scope_blocks)
    with_note = [e for e in entries if e["body"]]

    st.caption(
        f"File: `{scope_file}`  |  Scope: `{scope}`  |  {source_badge(result)}"
    )

    if not with_note:
        st.info(
            f"No compressed week note (section I) in `{scope_file}`. Notes "
            "written before the A-I format don't have one - read those in "
            "full on the Weekly Monitor tab."
        )
        return

    choices = _recap_week_choices(len(with_note))
    default = (_RECAP_DEFAULT_WEEKS if _RECAP_DEFAULT_WEEKS in choices
               else choices[-1])
    ctl = st.columns([2, 3])
    count = ctl[0].selectbox(
        "Weeks to show",
        options=choices,
        index=choices.index(default),
        key=f"wr_count_{scope}",
        help="Most recent weeks first, newest on the left.",
    )
    raw = ctl[1].checkbox(
        "Raw text",
        value=False,
        key=f"wr_raw_{scope}",
        help="Show the note exactly as stored, markdown syntax and all. "
             "Off renders it as written.",
    )

    shown = with_note[:count]

    # Subsection picker: the note's own ### parts (Regime / Scoreboard / Major
    # Release Tape / ...). Everything is selected by default; narrowing it
    # reads one part across several weeks instead of whole notes.
    titles = _recap_subsection_titles(shown)
    selected = None
    if titles:
        sec_key = f"wr_sections_{scope}"
        _seed_recap_sections(st.session_state, sec_key, titles)
        selected = st.multiselect(
            "Parts of the note to show",
            options=titles,
            key=sec_key,
            help="All parts by default. Narrow it to compare one part "
                 "week over week.",
        )

    skipped = len(entries) - len(with_note)
    if skipped:
        st.caption(
            f"{skipped} older week(s) in this file have no compressed note "
            "and are not shown here."
        )

    if titles and not selected:
        st.info("Select at least one part of the note to show.")
        return

    # Stacked top to bottom, most recent first -- a compressed note is a column
    # of prose, and side-by-side columns cut it too narrow to read.
    for i, entry in enumerate(shown):
        label = entry["label"] or (entry["block"].stem + " (no data window)")
        body = filter_subsections(entry["body"], selected)
        # `##`, so the week header outranks the note's own `###` subsections.
        st.markdown(f"## {label}")
        if not (body or "").strip():
            st.caption("None of the selected parts appear in this week's note.")
        elif raw:
            st.code(body, language="text", wrap_lines=True)
        else:
            st.markdown(_escape_importance_flags(body))
        if i < len(shown) - 1:
            st.divider()


# --- Weekly Monitor note views ---------------------------------------------
#
# The canonical WEEK object is a lettered spine A-I. A-H are the authoritative
# intelligence; I is a compressed derivative the note author wrote, which we
# display verbatim and never regenerate from A-H.
_WEEK_VIEW_PM = "PM view - compressed note (I)"
_WEEK_VIEW_ANALYSIS = "Full analysis (A, B, D-H)"
_WEEK_VIEW_ARCHIVE = "Release archive (C)"
_WEEK_VIEW_FULL = "Full note (A-I)"
_WEEK_VIEWS = [_WEEK_VIEW_PM, _WEEK_VIEW_ANALYSIS, _WEEK_VIEW_ARCHIVE, _WEEK_VIEW_FULL]

# Narrative sections each view renders as text. C (the release archive) is not
# listed: it is rendered as release cards, not as a raw body. D is included in
# the analysis views, where it replaces the standalone tape card.
_WEEK_VIEW_SECTIONS = {
    _WEEK_VIEW_PM: ["compressed"],
    _WEEK_VIEW_ANALYSIS: ["synthesis", "scoreboard", "central_bank_tape",
                          "signal_tension", "key_releases", "red_team",
                          "fx_consensus"],
    _WEEK_VIEW_ARCHIVE: [],
    _WEEK_VIEW_FULL: ["synthesis", "scoreboard", "central_bank_tape",
                      "signal_tension", "key_releases", "red_team",
                      "fx_consensus", "compressed"],
}

# Views that render the section-C release cards.
_WEEK_VIEWS_WITH_RELEASES = {_WEEK_VIEW_ARCHIVE, _WEEK_VIEW_FULL}


def _default_week_view(blocks):
    """Pick the Weekly Monitor's default note view for a set of weekly blocks.

    Section I is the intended quick view, but it only exists in the new note
    format -- every note written before it would render as a blank tab. So the
    PM view is the default only when at least one displayed week actually has
    an I, and otherwise we fall back to the release archive (the behaviour this
    tab has always had).
    """
    for b in blocks or []:
        if has_week_section(b, "compressed"):
            return _WEEK_VIEW_PM
    return _WEEK_VIEW_ARCHIVE


def _seed_week_view(session_state, key, default_view):
    """Seed the note-view picker without overriding a manual choice.

    Streamlit ignores a selectbox's `index=` once the keyed widget has a value
    in session_state, so the default has to be written in directly. Only writes
    when the key is absent, or when the previously seeded default has changed
    (i.e. the user moved to a scope/week whose format differs).
    """
    prev_key = key + "__seeded"
    if key not in session_state or session_state.get(prev_key) != default_view:
        session_state[key] = default_view
        session_state[prev_key] = default_view
    return session_state[key]


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

    # For an individual DM/EM currency, the regional bucket file
    # (DM_WEEK.txt / EM_WEEK.txt) may carry weeks more recent than the
    # currency's own frozen file. Fold those windows into the same entry
    # list -- being the newest they sort to the top and join the Week
    # selector -- showing ONLY this country's release cards for them
    # (no week summary, no central-bank tape, no narrative sections).
    regional_scope = ("DM" if scope in CURRENCY_SCOPES_DM
                      else "EM" if scope in CURRENCY_SCOPES_EM
                      else None)
    regional_file = (SCOPE_FILES.get(regional_scope, {}).get("frozen_week", "")
                     if regional_scope else "")
    scope_countries = set(SCOPE_COUNTRIES.get(scope, []))
    if regional_file and scope_countries:
        latest_end = max(
            (e["end"] or e["start"] for e in entries if e["end"] or e["start"]),
            default=None,
        )
        reg_result = _load_file(regional_file)
        if not reg_result.error and reg_result.text:
            reg_blocks = extract_blocks(
                reg_result.text, source_file=reg_result.filename
            )
            reg_blocks = ([b for b in reg_blocks if b.region == regional_scope]
                          or reg_blocks)
            _EXCLUDED_SECTIONS = set(NARRATIVE_SECTION_IDS) | {"central_bank_tape"}
            for b in reg_blocks:
                label, start, end = block_data_window(b)
                newest = end or start
                if newest is None:
                    continue
                if latest_end is not None and newest <= latest_end:
                    continue
                rels = [
                    r for r in dedup_releases(extract_releases(b))
                    if getattr(r, "section", "data") not in _EXCLUDED_SECTIONS
                    and scope_countries.intersection(r.countries or [])
                ]
                if rels:
                    entries.append({
                        "label": label, "block": b, "start": start, "end": end,
                        "regional_releases": rels, "source": regional_file,
                    })

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
            + (f"  -  {e['source']}" if e.get("source") else "")
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

    # Which parts of the lettered A-I spine to show. Default is the PM view
    # when the displayed weeks actually have a section I, else the release
    # archive (see _default_week_view).
    view_key = f"wm_note_view_{scope}_{view}"
    _seed_week_view(
        st.session_state, view_key,
        _default_week_view([e["block"] for e in selected_entries
                            if e.get("regional_releases") is None]),
    )
    note_view = st.selectbox(
        "Note view",
        options=_WEEK_VIEWS,
        key=view_key,
        help="A-H are the authoritative week object; I is the author's "
             "compressed PM version of it, shown verbatim. Notes predating "
             "the A-I format have only A, B, C plus unlettered narrative "
             "sections, and fall back to the release archive.",
    )
    show_releases = note_view in _WEEK_VIEWS_WITH_RELEASES

    if show_releases:
        sort_desc = st.checkbox(
            "Sort releases newest-first",
            value=False,
            key=f"wm_sort_{scope}_{view}",
            help="Off = chronological order (Mon to Fri). On = newest first.",
        )
    else:
        sort_desc = False

    min_importance = min(levels, key=len) if levels else None

    for entry in selected_entries:
        b = entry["block"]
        label = entry["label"]
        regional_rels = entry.get("regional_releases")
        suffix = f"  -  from `{entry['source']}`" if regional_rels is not None else ""
        if label:
            st.markdown(f"### Data window: {label}{suffix}")
        else:
            st.markdown(f"### {b.stem} (no data window declared){suffix}")

        if regional_rels is not None:
            # Regional supplement week: country-filtered release cards only.
            # These weeks are borrowed from the regional file and carry no
            # narrative spine of their own, so the note view doesn't apply.
            releases = list(regional_rels)
        else:
            # Narrative sections for the selected view, in the note's own
            # document order. The PM view opens expanded -- it exists to be
            # read at a glance.
            n_sections = render_week_note_sections(
                b, _WEEK_VIEW_SECTIONS[note_view],
                expanded=(note_view == _WEEK_VIEW_PM),
            )
            if not n_sections and not show_releases:
                missing = ("compressed note (I)" if note_view == _WEEK_VIEW_PM
                           else "narrative sections")
                st.info(
                    f"This week's note has no {missing}. It predates the A-I "
                    f"format - switch to `{_WEEK_VIEW_ARCHIVE}` to read it."
                )
            if not show_releases:
                continue

            if note_view == _WEEK_VIEW_ARCHIVE:
                # Per-week narrative summary (Synthesis / Scoreboard / Signal
                # Tension / Key Releases / Red Team), collapsed by default with
                # the scoreboard glyphs in the row. Sits between the data-window
                # header and the cards. Skipped in the Full note view, which
                # already renders those sections individually.
                render_week_summary(b)

            releases = extract_releases(b)
            # Dedup by stable key (country|normalized|date|importance) so the
            # same Reuters event parsed twice in the same archive doesn't
            # surface twice.
            releases = dedup_releases(releases)
        if min_importance:
            releases = filter_releases(releases, min_importance=min_importance)

        # The CENTRAL BANK TAPE section is grouped into a single card shown
        # AFTER the data releases, rather than as peer cards interleaved by
        # date. Split it out here.
        #
        # The narrative sections (E SIGNAL TENSION CHECK, F KEY RELEASES, G RED
        # TEAM, H MARKET-CONSENSUS SCAN, I COMPRESSED NOTE) only *reference*
        # releases -- they are commentary, not the release archive. Their
        # importance-flagged, country-dashed lines (e.g. "**** Japan - CGPI
        # (10 Jun)") otherwise get parsed as phantom peer release cards that
        # duplicate the real archive entries. Keep them out of the data stream.
        # NOTE: "archive" (section C) and "synthesis"/"scoreboard" (A/B) are
        # intentionally NOT excluded -- C carries the *real* releases.
        if regional_rels is not None:
            cb_releases = []
            data_releases = releases
            tape_text = ""
        else:
            cb_releases = [r for r in releases
                           if getattr(r, "section", "data") == "central_bank_tape"]
            data_releases = [r for r in releases
                             if getattr(r, "section", "data") != "central_bank_tape"
                             and getattr(r, "section", "data") not in NARRATIVE_SECTION_IDS]
            tape_text = extract_central_bank_tape_text(b)

        if not data_releases and not (cb_releases or tape_text):
            st.info("No releases at the selected importance in this week.")
            continue

        # Stable sort: by parsed date (asc by default), preserving original
        # order on ties (which mirrors how the source file is laid out).
        def _sort_key(idx_r):
            idx, r = idx_r
            d = parse_release_date(r.date_str) or _dt.date.min
            return (d, idx)

        indexed = list(enumerate(data_releases))
        indexed.sort(key=_sort_key, reverse=sort_desc)
        sorted_releases = [r for _, r in indexed]

        st.caption(f"{len(sorted_releases)} release(s) in this window")
        for r in sorted_releases:
            render_release_card(r, default_expanded=False)

        # Central Bank Tape last, as one grouped card. Only in the archive
        # view -- the analysis and full-note views already render section D
        # in its own right, and two copies of the tape is worse than none.
        if (cb_releases or tape_text) and note_view == _WEEK_VIEW_ARCHIVE:
            render_central_bank_tape(tape_text, cb_releases)


# Macro Synthesis cross-week view: signal expanders in this fixed order.
_SYNTH_SIGNAL_ORDER = [
    "Growth", "Labor", "Inflation", "Policy Constraint", "Financial Conditions",
]
_SYNTH_DEFAULT_WEEKS = 4


def tab_macro_synthesis(state):
    """Cross-week Macro Synthesis view for the selected scope.

    Compares the most recent N weeks (default 4, newest-first):
      - one expander gathering each week's A. MACRO SYNTHESIS prose, and
      - one expander per scoreboard signal (Growth, Labor, Inflation, Policy
        Constraint, Financial Conditions) gathering that signal's line and
        supporting evidence across the weeks.
    The release archive (C) and central bank tape are NOT shown here.
    """
    scope = state["scope"]
    scope_file = SCOPE_FILES.get(scope, {}).get("frozen_week", "")
    st.header(f"{scope} - Macro Synthesis")
    if not scope_file:
        st.info(f"No `Frozen week` file configured for `{scope}`.")
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
        st.info(f"No `{scope}` weekly blocks parsed from `{scope_file}`.")
        return

    st.caption(
        f"File: `{scope_file}`  |  Scope: `{scope}`  |  {source_badge(result)}"
    )

    # Week entries, newest-first.
    entries = []
    for b in scope_blocks:
        label, start, end = block_data_window(b)
        entries.append({"block": b, "label": label, "start": start, "end": end})
    entries.sort(key=lambda e: e["start"] or _dt.date.min, reverse=True)

    # How many recent weeks to compare (default 4).
    if len(entries) > 1:
        n_weeks = st.number_input(
            "Weeks to compare (most recent)",
            min_value=1,
            max_value=len(entries),
            value=min(_SYNTH_DEFAULT_WEEKS, len(entries)),
            step=1,
            key=f"ms_nweeks_{scope}",
        )
    else:
        n_weeks = 1
    recent = entries[: int(n_weeks)]

    parsed = [(e, extract_macro_synthesis(e["block"])) for e in recent]
    if not any(syn["synthesis"] or syn["signals"] for _e, syn in parsed):
        st.info(
            "No A/B synthesis sections found in the recent weeks. The file "
            "may not yet contain the synthesis layer for this window."
        )
        return

    def _wk(entry):
        return entry["label"] or entry["block"].stem

    # 1) MACRO SYNTHESIS prose across weeks (newest-first).
    syn_header = next(
        (syn["synthesis_header"] for _e, syn in parsed if syn["synthesis_header"]),
        f"{scope} WEEK — MACRO SYNTHESIS",
    )
    syn_label = syn_header
    if len(syn_label) > 3 and syn_label[0] in "ABCD" and syn_label[1:3] == ". ":
        syn_label = syn_label[3:]
    with st.expander(syn_label, expanded=False):
        any_syn = False
        for e, syn in parsed:
            if syn["synthesis"]:
                any_syn = True
                st.markdown(f"**{_wk(e)}**")
                st.code(syn["synthesis"], language="text", wrap_lines=True)
        if not any_syn:
            st.caption("No synthesis prose in the selected weeks.")

    # 2) One expander per scoreboard signal, in the requested order, each
    #    gathering that signal across the weeks (newest-first).
    for sig_name in _SYNTH_SIGNAL_ORDER:
        rows = []
        for e, syn in parsed:
            match = next((s for s in syn["signals"] if s[0] == sig_name), None)
            if match:
                rows.append((e, match))
        if not rows:
            continue
        latest_glyph = rows[0][1][1]
        with st.expander(f"{sig_name}: {latest_glyph}", expanded=False):
            for e, (name, glyph, evidence) in rows:
                st.markdown(f"**{_wk(e)}**")
                body = f"{name}: {glyph}\n{evidence}".rstrip()
                st.code(body, language="text", wrap_lines=True)

    # 3) KEY RELEASES TO DIG INTO across weeks (newest-first). The section
    #    name carries the count ("3 KEY RELEASES" / "5 KEY RELEASES"); use the
    #    latest week's header for the band label.
    kr_rows = [(e, syn) for e, syn in parsed if syn.get("key_releases")]
    if kr_rows:
        kr_label = next(
            (syn["key_releases_header"] for _e, syn in parsed
             if syn.get("key_releases_header")),
            "KEY RELEASES TO DIG INTO",
        )
        with st.expander(kr_label, expanded=False):
            for e, syn in kr_rows:
                st.markdown(f"**{_wk(e)}**")
                st.code(syn["key_releases"], language="text", wrap_lines=True)


_MACRO_NOTE_VIEWS = ["Latest note only", "Previous notes", "All notes archive"]


_AS_OF_RE = re.compile(r"^\s*As of:\s*(.+?)\s*$", re.MULTILINE)


def _note_as_of_date(block):
    """Parse the `As of:` version stamp at the top of a macro note.

    This is the authoritative version date and is always written in a clean,
    parseable form (e.g. "30 June 2026"). It is preferred over the block's
    `Data window:` end date, which can be fuzzy prose like
    "late May to late June 2026" that `parse_release_date` cannot parse.
    Returns a date or None.
    """
    if block is None or not getattr(block, "raw_text", ""):
        return None
    m = _AS_OF_RE.search(block.raw_text)
    if not m:
        return None
    return parse_release_date(m.group(1))


def _macro_note_versions(blocks):
    """Order parsed note blocks (in document order) so the most recent
    version is first.

    Files store the newest note ON TOP, so document order alone already puts
    the latest first. To be robust we sort by the `As of:` version date when
    present, then the data-window end date, then reverse document order so the
    top-of-file note wins any remaining tie. Notes whose `As of:` date cannot
    be parsed fall back to those secondary keys rather than sinking to the
    bottom, which previously caused a newer note with fuzzy `Data window:`
    prose (e.g. "late May to late June 2026") to be ranked below an older
    note that happened to have a clean, parseable window.
    """
    annotated = []
    for i, b in enumerate(blocks):
        label, start, end = block_data_window(b)
        as_of = _note_as_of_date(b)
        annotated.append((b, label, start, end, i, as_of))
    annotated.sort(
        key=lambda x: (
            x[5] or _dt.date.min,  # As of: version date desc primary
            x[3] or _dt.date.min,  # data-window end-date desc tiebreak
            -x[4],                 # top-of-file (earlier index) wins final ties
        ),
        reverse=True,
    )
    # Preserve the original 5-tuple shape expected by callers.
    return [(b, label, start, end, i) for (b, label, start, end, i, _as_of) in annotated]


def _seed_macro_note_picker(session_state, sidebar_scope, note_options):
    """Keep the Macro Notes file picker following the sidebar scope.

    Streamlit ignores a selectbox's `index=` argument once that keyed widget
    already has a value in session_state, so on reruns the picker would stay
    stuck on whatever file it first showed even after the user changes the
    sidebar scope. This re-seeds `mn_select` to the scope's own macro note
    whenever the sidebar scope changes to a scope that HAS one.

    Behavior:
      - First render, or scope changed to one with its own note -> seed to it.
      - Scope changed to one with NO note (e.g. CAD) -> leave the current pick.
      - Same scope across reruns -> leave the user's manual pick untouched.

    Mutates `session_state` in place; returns the resolved default index.
    """
    matched_idx = None
    for i, (s, _) in enumerate(note_options):
        if s == sidebar_scope:
            matched_idx = i
            break
    default_idx = matched_idx if matched_idx is not None else 0
    if session_state.get("mn_last_scope") != sidebar_scope:
        session_state["mn_last_scope"] = sidebar_scope
        if matched_idx is not None:
            session_state["mn_select"] = matched_idx
    if "mn_select" not in session_state:
        session_state["mn_select"] = default_idx
    return default_idx


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
    # scope (e.g. sidebar=USD -> USD_MACRO_NOTE.txt). Streamlit ignores the
    # `index=` arg once a keyed widget's value lives in session_state, so this
    # helper re-seeds `mn_select` whenever the sidebar scope changes.
    sidebar_scope = (state or {}).get("scope", "")
    _seed_macro_note_picker(st.session_state, sidebar_scope, note_options)

    cols = st.columns([3, 2])
    labels = [f"{s}  -  {fn}" for s, fn in note_options]
    idx = cols[0].selectbox(
        "Macro note file",
        options=list(range(len(note_options))),
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

    blocks = extract_macro_note_versions(result.text, source_file=result.filename)
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
        if latest_label:
            st.caption(f"Data window: {latest_label}")
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
    """Collapse duplicate occurrences without ever silently losing a release.

    Caller must order `releases` so the preferred occurrence comes first
    (frozen before live -- the catalogue orders `allowed_files` frozen-first).

    Three narrow rules:

    * No `catalogue_key` (reference_period couldn't be inferred) -> always
      kept. We never merge unrelated releases just because the period is
      unknown.
    * Same `catalogue_key` from a DIFFERENT source file -> the same event
      parsed twice, live and frozen. Collapse; frozen wins by ordering.
    * Same `catalogue_key` AND same `release_key` within one file -> a true
      duplicate parse of one event. Collapse.

    What is deliberately NOT collapsed: two releases sharing a catalogue_key
    *within the same file* but differing in date or importance. Those are
    different releases the normalizer hasn't learned to tell apart yet
    (Nationwide vs Halifax house prices, New vs Existing home sales,
    Nationwide vs Tokyo CPI). The old rule collapsed them on
    (country, name, period) alone, which silently dropped 41 rows from the
    real archive with nothing in the UI to indicate anything was missing.
    A duplicate-looking row is a much better failure than a vanished release.
    """
    ck_file = {}
    seen_rk = set()
    out = []
    for r in releases or []:
        k = catalogue_key(r)
        if not k:
            out.append(r)
            continue
        rk = release_key(r)
        if rk and rk in seen_rk:
            continue
        first_file = ck_file.get(k)
        this_file = getattr(r, "source_file", "")
        if first_file is not None and first_file != this_file:
            continue
        ck_file.setdefault(k, this_file)
        if rk:
            seen_rk.add(rk)
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
# (sb_group, sb_scope, sb_view, sb_levels, sb_time_window) and
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
    new_country = default_catalogue_country(new_scope)
    if new_country:
        session["cc_country"] = new_country
    session["_prev_scope"] = new_scope
    return session


def _handle_scope_change(scope):
    """If sidebar scope changed since the last render, reset tab state and rerun.

    First render: just records the scope, no reset. Subsequent renders: on
    real change, reset and rerun so widgets pick up new defaults. Returns
    True when a reset happened.
    """
    prev = st.session_state.get("_prev_scope")
    if prev is None:
        # First render: don't reset tab state, but DO seed cc_country so
        # the Catalogue tab opens on the sidebar scope's representative
        # country (USD -> US, EUR -> Eurozone, GBP -> UK ...).
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

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Week Recap",
        "Weekly Monitor",
        "Macro Synthesis",
        "Macro Notes",
        "Country Release Catalogue",
    ])
    with tab1:
        tab_week_recap(state)
    with tab2:
        tab_weekly_monitor(state)
    with tab3:
        tab_macro_synthesis(state)
    with tab4:
        tab_macro_notes(state)
    with tab5:
        tab_country_release_catalogue()


if __name__ == "__main__":
    main()
