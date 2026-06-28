"""Regression test: the Macro Notes file picker must follow the sidebar scope.

Bug: selecting BRL in the sidebar left the Macro Notes tab on USD_MACRO_NOTE.
Streamlit ignores a keyed selectbox's `index=` once the widget value is in
session_state, so the picker stayed stuck on the first render's file.
_seed_macro_note_picker re-seeds `mn_select` when the sidebar scope changes.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit_app

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


seed = streamlit_app._seed_macro_note_picker

# (scope, filename) options in ALL_SCOPES order; index() lets us assert by name.
from core.config import ALL_SCOPES, SCOPE_FILES  # noqa: E402
note_options = [
    (scope, SCOPE_FILES[scope]["macro_note"])
    for scope in ALL_SCOPES
    if SCOPE_FILES[scope].get("macro_note")
]
def idx_of(scope):
    return next(i for i, (s, _) in enumerate(note_options) if s == scope)

# Sanity: both USD and BRL have macro notes configured.
expect("USD note option exists", any(s == "USD" for s, _ in note_options))
expect("BRL note option exists", any(s == "BRL" for s, _ in note_options))


# 1. First render with sidebar scope = BRL seeds the picker to BRL, not USD.
ss = {}
seed(ss, "BRL", note_options)
expect("first render BRL -> picker on BRL",
       ss["mn_select"] == idx_of("BRL"),
       f"got {ss['mn_select']}, want {idx_of('BRL')}")

# 2. THE BUG: start on USD, then user switches sidebar to BRL on a later
#    rerun. Even though mn_select already holds the USD index, the picker
#    must move to BRL.
ss = {}
seed(ss, "USD", note_options)            # first render
expect("USD first render -> USD", ss["mn_select"] == idx_of("USD"))
seed(ss, "BRL", note_options)            # rerun after scope change
expect("scope change USD->BRL re-seeds to BRL",
       ss["mn_select"] == idx_of("BRL"),
       f"got {ss['mn_select']}, want {idx_of('BRL')}")

# 3. A manual pick within the SAME scope is preserved across reruns.
ss = {}
seed(ss, "BRL", note_options)
ss["mn_select"] = idx_of("USD")          # user manually picks USD while on BRL
seed(ss, "BRL", note_options)            # rerun, same scope -> don't stomp it
expect("same-scope rerun keeps manual pick",
       ss["mn_select"] == idx_of("USD"),
       f"got {ss['mn_select']}")

# 4. Switching to a scope with NO macro note (e.g. CAD) leaves the pick alone.
no_note_scope = next(
    (s for s in ALL_SCOPES if not SCOPE_FILES[s].get("macro_note")), None)
expect("there is a note-less scope to test", no_note_scope is not None)
if no_note_scope:
    ss = {}
    seed(ss, "BRL", note_options)
    before = ss["mn_select"]
    seed(ss, no_note_scope, note_options)
    expect("scope with no note leaves picker unchanged",
           ss["mn_select"] == before,
           f"got {ss['mn_select']}, want {before}")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
