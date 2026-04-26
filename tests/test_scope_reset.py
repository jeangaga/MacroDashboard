"""Regression tests for tasks #49-#51:

Scope is a global state driver. When sidebar scope changes (USD -> EUR),
every tab forgets its prior selections so defaults re-derive from the new
scope.

We avoid spinning up Streamlit by exercising the pure helpers
(_reset_state_for_scope, default_catalogue_country) with an injected dict
in place of st.session_state.
"""
import sys, inspect
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

PASS = 0
FAIL = 0
def expect(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok - {label}")
    else:
        FAIL += 1
        print(f"  FAIL - {label}  {detail}")


# ---------------------------------------------------------------------------
# 1. default_catalogue_country covers every scope the sidebar can produce.
# ---------------------------------------------------------------------------
from core.config import (  # noqa: E402
    REGION_SCOPES, CURRENCY_SCOPES_DM, CURRENCY_SCOPES_EM, PM_SCOPES,
    SCOPE_COUNTRIES, COUNTRY_SOURCE_PRIORITY,
    default_catalogue_country,
)

expected_region = {
    "USD": "US",
    "EUR": "Eurozone",   # explicit regional default per UX spec
    "DM":  "UK",
    "EM":  "China",
}
for scope, want in expected_region.items():
    got = default_catalogue_country(scope)
    expect(f"region scope {scope} -> {want}", got == want, f"got {got!r}")

# Currency scopes resolve to the single country they map to in SCOPE_COUNTRIES,
# provided that country has a COUNTRY_SOURCE_PRIORITY entry.
for cs in (*CURRENCY_SCOPES_DM, *CURRENCY_SCOPES_EM):
    countries = SCOPE_COUNTRIES.get(cs) or []
    expected = next((c for c in countries if c in COUNTRY_SOURCE_PRIORITY), None)
    got = default_catalogue_country(cs)
    expect(f"currency scope {cs} -> {expected!r}", got == expected,
           f"got {got!r}")

# PM/shared scopes have no countries, so the helper returns None and the
# Catalogue tab keeps whatever country was previously selected.
for pm in PM_SCOPES:
    got = default_catalogue_country(pm)
    expect(f"PM scope {pm} -> None", got is None, f"got {got!r}")

# Defensive: empty / unknown scope must not crash.
expect("empty scope -> None", default_catalogue_country("") is None)
expect("None scope -> None", default_catalogue_country(None) is None)
expect("unknown scope -> None", default_catalogue_country("ZZZ") is None)


# ---------------------------------------------------------------------------
# 2. _reset_state_for_scope clears tab-local widget keys but leaves sidebar
#    keys, the refresh token, and unrelated user state alone.
# ---------------------------------------------------------------------------
import streamlit_app  # noqa: E402

reset_keys = streamlit_app._SCOPE_RESET_KEYS
expect("_SCOPE_RESET_KEYS is a tuple of strings",
       isinstance(reset_keys, tuple) and all(isinstance(k, str) for k in reset_keys))
# Sanity: cover every tab.
for required in ("mn_select", "mn_view_mode",
                 "rs_query", "rs_scopes", "rs_themes", "rs_levels",
                 "rs_window", "rs_rtypes", "rs_countries", "rs_view_mode",
                 "tm_theme", "tm_window", "tm_levels", "tm_scopes", "tm_countries",
                 "cc_country", "cc_themes", "cc_search",
                 "cc_include_live", "cc_only_known", "cc_table"):
    expect(f"reset list contains {required}", required in reset_keys)
# Must NOT leak into sidebar / global keys.
for forbidden in ("sb_group", "sb_scope", "sb_view", "sb_levels",
                  "sb_themes", "sb_time_window", "refresh_token"):
    expect(f"reset list excludes {forbidden}", forbidden not in reset_keys)

# Build a fake session populated with the kinds of keys the app produces.
fake_session = {
    # tab-local state the user fiddled with under USD
    "mn_select": 0,
    "mn_view_mode": "All notes archive",
    "rs_query": "CPI",
    "rs_scopes": ["USD"],
    "rs_levels": ["****"],
    "rs_window": "Last 4 weeks",
    "tm_theme": "Inflation",
    "tm_scopes": ["USD"],
    "cc_country": "US",
    "cc_themes": ["Labor"],
    "cc_include_live": True,
    "cc_only_known": True,
    "cc_table": {"selection": {"rows": [3]}},
    # global state we must not clobber
    "sb_group": "Region",
    "sb_scope": "USD",
    "sb_levels": ["***", "****"],
    "sb_time_window": "All",
    "refresh_token": 7,
    "active_command": {"query": "CPI", "regions": ["USD"]},
    # tracker the helper itself writes
    "_prev_scope": "USD",
    # something unrelated the user might have set
    "show_cmd_help": True,
}
before_keys = set(fake_session.keys())

returned = streamlit_app._reset_state_for_scope("EUR", session=fake_session)
expect("_reset_state_for_scope returns the same session dict",
       returned is fake_session)

# Tab-local keys are gone.
for key in ("mn_select", "rs_query", "rs_scopes", "rs_levels", "tm_theme",
            "tm_scopes", "cc_themes", "cc_only_known", "cc_table"):
    expect(f"{key} cleared", key not in fake_session,
           f"still present: {fake_session.get(key)!r}")

# Sidebar / unrelated keys intact.
expect("sb_group preserved", fake_session.get("sb_group") == "Region")
expect("sb_scope preserved", fake_session.get("sb_scope") == "USD")
expect("sb_levels preserved", fake_session.get("sb_levels") == ["***", "****"])
expect("sb_time_window preserved", fake_session.get("sb_time_window") == "All")
expect("refresh_token preserved", fake_session.get("refresh_token") == 7)
expect("show_cmd_help preserved", fake_session.get("show_cmd_help") is True)

# active_command is wiped (carries stale region filters).
expect("active_command reset to empty dict",
       fake_session.get("active_command") == {},
       f"got {fake_session.get('active_command')!r}")

# Catalogue is pre-seeded to the new scope's representative country.
expect("cc_country re-seeded to Eurozone for EUR",
       fake_session.get("cc_country") == "Eurozone",
       f"got {fake_session.get('cc_country')!r}")

# Tracker advanced.
expect("_prev_scope advanced to EUR", fake_session.get("_prev_scope") == "EUR")


# ---------------------------------------------------------------------------
# 3. Reset is a no-op shape on PM scopes (no representative country to seed)
#    and on a scope that has no resident country mapping.
# ---------------------------------------------------------------------------
fake_session_pm = {
    "cc_country": "Germany",  # leftover from EUR session
    "rs_query": "stale",
    "_prev_scope": "EUR",
}
streamlit_app._reset_state_for_scope("WEEKPM", session=fake_session_pm)
expect("PM scope: rs_query cleared",
       "rs_query" not in fake_session_pm)
# cc_country is cleared along with the rest of the catalogue keys; PM scopes
# leave it absent rather than reseed it. The widget will fall back to its
# alphabetical-first option on next render.
expect("PM scope: cc_country not reseeded",
       "cc_country" not in fake_session_pm,
       f"still {fake_session_pm.get('cc_country')!r}")
expect("PM scope: _prev_scope advanced",
       fake_session_pm.get("_prev_scope") == "WEEKPM")


# ---------------------------------------------------------------------------
# 4. cc_country seeded country differs per scope.
# ---------------------------------------------------------------------------
for scope, want in [("USD", "US"), ("EUR", "Eurozone"),
                    ("GBP", "UK"), ("JPY", "Japan"),
                    ("CNH", "China"), ("AUD", "Australia"),
                    ("DM", "UK"), ("EM", "China")]:
    sess = {"_prev_scope": "PREV"}
    streamlit_app._reset_state_for_scope(scope, session=sess)
    expect(f"scope {scope} seeds cc_country={want!r}",
           sess.get("cc_country") == want,
           f"got {sess.get('cc_country')!r}")


# ---------------------------------------------------------------------------
# 5. main() wires the scope-change handler in BEFORE rendering tabs, and the
#    "Current scope:" indicator is present.
# ---------------------------------------------------------------------------
main_src = inspect.getsource(streamlit_app.main)
expect("main() calls _handle_scope_change after sidebar()",
       "_handle_scope_change(state[\"scope\"])" in main_src
       or "_handle_scope_change(state['scope'])" in main_src,
       "no _handle_scope_change(state['scope']) call in main()")
expect("main() renders 'Current scope:' indicator",
       "Current scope:" in main_src,
       "no 'Current scope:' caption in main()")

# Order: _handle_scope_change must run before the tabs are constructed so a
# rerun aborts the render cleanly with a fresh state.
i_handle = main_src.find("_handle_scope_change")
i_tabs = main_src.find("st.tabs(")
expect("scope-change runs before st.tabs()",
       0 < i_handle < i_tabs,
       f"i_handle={i_handle}, i_tabs={i_tabs}")


# ---------------------------------------------------------------------------
# 6. _handle_scope_change is callable and short-circuits on unchanged scope
#    (we cannot exercise st.rerun() from a unit test, so we only verify the
#    no-change branch returns False without raising).
# ---------------------------------------------------------------------------
import streamlit as _streamlit  # noqa: E402
# Drive st.session_state via the real object so the helper sees a mapping.
_streamlit.session_state["_prev_scope"] = "USD"
res = streamlit_app._handle_scope_change("USD")
expect("_handle_scope_change('same') returns False", res is False)
# First-render path: clear, then call -> records scope without resetting.
del _streamlit.session_state["_prev_scope"]
res = streamlit_app._handle_scope_change("EUR")
expect("_handle_scope_change first run returns False",
       res is False)
expect("_handle_scope_change records scope on first run",
       _streamlit.session_state.get("_prev_scope") == "EUR")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
