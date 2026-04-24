"""Macro FX Feed Dashboard - Streamlit entry point.

Run:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import streamlit as st

from core.config import (
    ALL_NOTE_FILES,
    ALL_SCOPES,
    ALL_THEMES,
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
)
from core.loaders import LoadResult, load_file, load_many
from core.parsers import extract_blocks, releases_from_load_results
from core.render import (
    importance_chip,
    render_block,
    render_load_status,
    render_release_list,
    source_badge,
)
from core.search import (
    filter_releases,
    inflation_releases,
    parse_command,
    releases_to_dataframe,
)

st.set_page_config(
    page_title="Macro FX Feed Dashboard",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)


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
    )
    group_options = {
        "Region":       REGION_SCOPES,
        "DM currency":  CURRENCY_SCOPES_DM,
        "EM currency":  CURRENCY_SCOPES_EM,
        "PM / shared":  PM_SCOPES,
    }[group]
    scope = st.sidebar.selectbox("Scope", options=group_options, index=0, label_visibility="collapsed")

    st.sidebar.subheader("View")
    views = _available_views(scope)
    if views:
        view_labels = [_view_display(k) for k, _ in views]
        view_idx = st.sidebar.radio(
            "View", options=list(range(len(views))),
            format_func=lambda i: view_labels[i],
            label_visibility="collapsed",
        )
        view = views[view_idx][0]
    else:
        view = "frozen_week"
        st.sidebar.caption("No views available for this scope.")

    st.sidebar.subheader("Importance")
    importance_choice = st.sidebar.radio(
        "Importance",
        options=["All", "*** + ****", "**** only"],
        index=1, label_visibility="collapsed",
    )
    min_importance = {"All": None, "*** + ****": "***", "**** only": "****"}[importance_choice]

    st.sidebar.subheader("Themes")
    themes = st.sidebar.multiselect(
        "Themes", options=ALL_THEMES, default=[], label_visibility="collapsed",
    )

    st.sidebar.divider()
    if st.sidebar.button("Refresh from GitHub", use_container_width=True):
        st.session_state["refresh_token"] = _refresh_token() + 1
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption(f"Cache token: {_refresh_token()}")

    return {
        "scope": scope,
        "view": view,
        "min_importance": min_importance,
        "themes": themes,
    }


_CMD_HELP = """
**Command syntax** — type any combination, order doesn't matter.

| What you type | Effect |
|---|---|
| `CPI US` | Keyword `CPI`, scope `USD` |
| `CPI Australia` | Keyword `CPI`, scope `AUD` |
| `inflation EM` | Theme `Inflation`, scope `EM` |
| `**** inflation EM` | Importance `****`, theme `Inflation`, scope `EM` |
| `QUICK EUR` | All `***+` releases for EUR |
| `QUICK2US` | All `****` releases for USD |
| `labor Japan` | Theme `Labor`, scope `JPY` |
| `retail UK CPI` | Keyword `retail CPI`, scope `GBP` |

**Scopes** — regions: `USD EUR DM EM`;
DM currencies: `AUD CAD CHF GBP JPY NOK SEK`;
EM currencies: `BRL CNH INR KRW MXN PLN TRY TWD ZAR`;
PM files: `WEEKPM MACROPM SHORT_WEEK ARC`.

**Aliases** — `US` = `USD`, `UK` = `GBP`, `EU` = `EUR`, `Japan` = `JPY`,
`China` = `CNH`, `Brazil` = `BRL`, `Australia` = `AUD`, etc.

**Importance** — `*` through `****` sets the minimum stars.

**Themes** — any theme name from the sidebar list.

Everything else becomes a free-text keyword search over title + body.
""".strip()


def command_bar():
    if "active_command" not in st.session_state:
        st.session_state["active_command"] = {}
    if "show_cmd_help" not in st.session_state:
        st.session_state["show_cmd_help"] = False

    with st.container(border=True):
        cols = st.columns([6, 1, 1, 1])
        cmd = cols[0].text_input(
            "Command",
            value="",
            label_visibility="collapsed",
            placeholder="CPI US  |  **** inflation EM  |  QUICK EUR  |  labor Japan",
        )
        go = cols[1].button("Run", use_container_width=True)
        help_clicked = cols[2].button("?", use_container_width=True, help="Show command syntax")
        clear_clicked = cols[3].button("Clear", use_container_width=True, help="Clear active command")

        if help_clicked:
            st.session_state["show_cmd_help"] = not st.session_state["show_cmd_help"]
        if clear_clicked:
            st.session_state["active_command"] = {}
        if st.session_state["show_cmd_help"]:
            st.markdown(_CMD_HELP)

    if go and cmd.strip():
        parsed = parse_command(cmd)
        parsed["_raw"] = cmd.strip()
        st.session_state["active_command"] = parsed
        return parsed
    return st.session_state["active_command"]


def _command_summary(cmd):
    if not cmd:
        return ""
    bits = []
    if cmd.get("regions"):
        bits.append("scopes=" + ",".join(cmd["regions"]))
    if cmd.get("min_importance"):
        bits.append("importance>=" + cmd["min_importance"])
    if cmd.get("themes"):
        bits.append("themes=" + ",".join(cmd["themes"]))
    if cmd.get("query"):
        bits.append("query=" + repr(cmd["query"]))
    return "  |  ".join(bits) if bits else "(no filters parsed)"


def render_command_results(command_state):
    if not command_state:
        return
    # filter-relevant keys only
    relevant = {k: v for k, v in command_state.items() if k in {"query", "regions", "min_importance", "themes"} and v}
    if not relevant:
        st.info(
            "Command parsed but produced no filters. "
            "Try something like `CPI US` or `**** inflation EM`."
        )
        return

    st.divider()
    hdr_cols = st.columns([4, 1])
    raw = command_state.get("_raw", "")
    hdr_cols[0].subheader(f"Command results: `{raw}`")
    hdr_cols[0].caption(_command_summary(command_state))
    hdr_cols[1].caption("Filters apply across the whole archive.")

    all_results = _load_many(ALL_NOTE_FILES)
    all_releases = releases_from_load_results(all_results)
    filtered = filter_releases(all_releases, **relevant)
    render_release_list(filtered, limit=100, empty_message="No releases match this command.")


def tab_weekly_monitor(state):
    scope = state["scope"]
    view = state["view"]
    min_importance = state["min_importance"]
    scope_file = SCOPE_FILES.get(scope, {}).get(view, "")

    header_cols = st.columns([3, 1])
    header_cols[0].header(f"{scope} - {_view_display(view)}")
    if min_importance:
        header_cols[1].metric("Importance filter", importance_chip(min_importance))

    if not scope_file:
        st.warning(f"No `{_view_display(view)}` file configured for `{scope}`.")
        return

    result = _load_file(scope_file)
    st.caption(f"Loaded `{scope_file}`  {source_badge(result)}")
    if result.error:
        st.warning(result.error)
    if not result.text:
        st.info(f"No content available for `{scope_file}`.")
        return

    blocks = extract_blocks(result.text, source_file=result.filename)
    scope_blocks = [b for b in blocks if b.region == scope] or blocks
    for b in scope_blocks:
        render_block(b, min_importance=min_importance)


def tab_macro_notes():
    st.header("Macro Notes")
    note_options = [
        (scope, SCOPE_FILES[scope]["macro_note"])
        for scope in ALL_SCOPES
        if SCOPE_FILES[scope].get("macro_note")
    ]
    if not note_options:
        st.info("No macro note files configured.")
        return

    labels = [f"{s}  -  {fn}" for s, fn in note_options]
    idx = st.selectbox(
        "Select a macro note",
        options=list(range(len(note_options))),
        format_func=lambda i: labels[i],
    )
    scope, filename = note_options[idx]
    result = _load_file(filename)
    st.caption(f"Loaded `{filename}`  {source_badge(result)}")
    if result.error:
        st.warning(result.error)
    if not result.text:
        st.info(f"No content available for `{filename}`.")
        return
    blocks = extract_blocks(result.text, source_file=result.filename)
    for b in blocks:
        st.markdown(f"**{b.stem}**  scope `{b.region or '-'}`")
        st.code(b.raw_block if hasattr(b, "raw_block") else b.raw_text, language="text", wrap_lines=True)


def tab_release_search(sidebar_state, command_state):
    st.header("Release Search")
    all_results = _load_many(ALL_NOTE_FILES)
    render_load_status(all_results)
    all_releases = releases_from_load_results(all_results)

    if not all_releases:
        st.info(
            "No releases parsed yet. Either the repo files are empty, no markers are "
            "present, or GitHub is unreachable and there's no cache."
        )
        return

    default_scopes = [sidebar_state["scope"]] if sidebar_state["scope"] else []
    merged = dict(
        query="",
        regions=default_scopes,
        min_importance=sidebar_state["min_importance"],
        themes=sidebar_state["themes"],
    )
    merged.update({k: v for k, v in command_state.items() if v and k != "_raw"})

    with st.container(border=True):
        cols = st.columns([3, 2, 1, 1])
        query = cols[0].text_input(
            "Keyword search", value=merged.get("query", ""),
            placeholder="Australia CPI | labor US | RBA minutes",
        )
        scope_filter = cols[1].multiselect(
            "Scopes", options=ALL_SCOPES,
            default=merged.get("regions", []),
            format_func=_scope_label,
        )
        importance_options = ["Any", "*", "**", "***", "****"]
        default_importance = merged.get("min_importance")
        importance_idx = (
            importance_options.index(default_importance)
            if default_importance in importance_options[1:] else 0
        )
        importance_filter = cols[2].selectbox(
            "Min importance", options=importance_options, index=importance_idx,
        )
        themes_filter = cols[3].multiselect(
            "Themes", options=ALL_THEMES, default=merged.get("themes", []),
        )

    min_imp = None if importance_filter == "Any" else importance_filter
    countries_options = sorted({
        c for s in (scope_filter or ALL_SCOPES) for c in SCOPE_COUNTRIES.get(s, [])
    })
    countries_filter = st.multiselect("Countries", options=countries_options, default=[])

    results = filter_releases(
        all_releases,
        query=query,
        regions=scope_filter,
        min_importance=min_imp,
        themes=themes_filter,
        countries=countries_filter,
    )

    st.divider()
    view_cols = st.columns([1, 3])
    view_mode = view_cols[0].radio(
        "View", options=["Cards", "Table"], horizontal=True, label_visibility="collapsed",
    )
    if view_mode == "Cards":
        render_release_list(results, limit=200)
    else:
        df = releases_to_dataframe(results)
        display_df = df[[
            "importance", "region", "title", "date_str",
            "countries_str", "themes_str", "source_file",
        ]].rename(columns={
            "importance": "Imp", "region": "Scope", "title": "Title",
            "date_str": "Date", "countries_str": "Countries",
            "themes_str": "Themes", "source_file": "File",
        })
        st.dataframe(display_df, use_container_width=True, height=480)


def tab_inflation_monitor(sidebar_state):
    st.header("Inflation Monitor")
    st.caption(
        "Preset view over CPI / HICP / PPI / WPI / PCE / wages / unit labor cost / "
        "import & export prices / inflation expectations."
    )
    all_results = _load_many(ALL_NOTE_FILES)
    render_load_status(all_results)
    all_releases = releases_from_load_results(all_results)
    if not all_releases:
        st.info("No releases to filter yet.")
        return

    cols = st.columns([2, 1, 1])
    scope_filter = cols[0].multiselect(
        "Scopes", options=ALL_SCOPES,
        default=[sidebar_state["scope"]] if sidebar_state["scope"] else [],
        format_func=_scope_label,
    )
    importance_filter = cols[1].selectbox(
        "Min importance", options=["Any", "**", "***", "****"], index=2,
    )
    countries_options = sorted({
        c for s in (scope_filter or ALL_SCOPES) for c in SCOPE_COUNTRIES.get(s, [])
    })
    countries_filter = cols[2].multiselect("Countries", options=countries_options, default=[])

    base = inflation_releases(all_releases)
    min_imp = None if importance_filter == "Any" else importance_filter
    filtered = filter_releases(
        base, regions=scope_filter, min_importance=min_imp, countries=countries_filter,
    )
    render_release_list(filtered, limit=200)


def main():
    state = sidebar()
    st.title("Macro FX Feed Dashboard")
    st.caption(
        "Structured macro terminal over the GitHub-hosted archive. "
        "Sidebar scopes the view; the command bar runs QUICK-style shortcuts across all files."
    )
    command_state = command_bar()
    render_command_results(command_state)

    tab1, tab2, tab3, tab4 = st.tabs([
        "Weekly Monitor", "Macro Notes", "Release Search", "Inflation Monitor",
    ])
    with tab1:
        tab_weekly_monitor(state)
    with tab2:
        tab_macro_notes()
    with tab3:
        tab_release_search(state, command_state)
    with tab4:
        tab_inflation_monitor(state)


if __name__ == "__main__":
    main()
