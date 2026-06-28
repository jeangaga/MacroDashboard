"""Regression tests for two fixes:

1. Macro-note marker regex must be greedy so a file with an inner
   `<<STEM_END>>` (section divider after the brief summary) and a final
   `<<<STEM_END>>>` (triple-bracket terminator) captures the FULL block,
   not just the brief summary.

2. _handle_scope_change must seed cc_country on first render so the
   Catalogue tab opens on the sidebar scope's representative country
   (USD -> US, EUR -> Eurozone, etc.) instead of falling back to
   alphabetical first ("Australia").
"""
import sys
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
# 1. Greedy marker regex captures full block.
# ---------------------------------------------------------------------------
from core.parsers import extract_blocks  # noqa: E402

TEXT = """\
preamble before the marker (file-level junk)

<<USD_MACRO_NOTE_BEGIN>>

Data window: 30 Mar 2026 to 3 Apr 2026
Mild stagflationary deterioration became more explicit.

Trigger Map

More dovish / easier policy / cuts pulled forward
The next CPI / PCE block fails to validate the March cost shock.

Hold-longer / mildly hawkish reweighting
CPI / PCE confirms that the recent pipeline re-heating is passing into core.

Bottom Line

The U.S. is no longer best framed as a clean soft landing.

<<USD_MACRO_NOTE_END>>

Executive Summary
Top-Down Macro

Fed / Rates / USD
USD: supported by growth floor and pause optionality.

Cross-Market - Rates / FX / Risk Attribution
Rates: front-end anchored by cut-to-neutral then pause.

<<<USD_MACRO_NOTE_END>>>
"""

blocks = extract_blocks(TEXT, source_file="USD_MACRO_NOTE.txt")
expect("one block parsed", len(blocks) == 1, f"got {len(blocks)}")
block = blocks[0] if blocks else None
expect("data window captured",
       block is not None and block.data_window == "30 Mar 2026 to 3 Apr 2026",
       f"got {block.data_window if block else 'no block'}")

# All sections from BEGIN through the FINAL triple-END must be present.
required_sections = [
    "Mild stagflationary deterioration",   # brief summary (was working before)
    "Trigger Map",
    "More dovish / easier policy",
    "Hold-longer / mildly hawkish",
    "Bottom Line",
    # Sections AFTER the inner <<STEM_END>> -- these were silently dropped
    # by the lazy regex.
    "Executive Summary",
    "Top-Down Macro",
    "Fed / Rates / USD",
    "supported by growth floor",
    "Cross-Market",
    "front-end anchored",
]
for needle in required_sections:
    expect(f"block contains {needle!r}",
           block is not None and needle in block.raw_text,
           f"missing")


# Multi-block files (separate BEGIN/END pairs) still work -- only one pair
# in this test, but verify a single-pair file behaves identically.
SIMPLE = """\
<<USD_WEEK_BEGIN>>
Some weekly content.
<<USD_WEEK_END>>
"""
b2 = extract_blocks(SIMPLE, source_file="USD_WEEK.txt")
expect("single-pair file parses to one block",
       len(b2) == 1, f"got {len(b2)}")
expect("single-pair raw_text matches",
       b2[0].raw_text.strip() == "Some weekly content."
       if b2 else False,
       f"got {b2[0].raw_text!r}" if b2 else "no block")


# ---------------------------------------------------------------------------
# 2. _handle_scope_change seeds cc_country on first render.
# ---------------------------------------------------------------------------
import streamlit as _streamlit  # noqa: E402
import streamlit_app  # noqa: E402

# Clear any state left over from earlier tests.
for k in list(_streamlit.session_state.keys()):
    del _streamlit.session_state[k]

# First render with USD scope -> cc_country should be seeded to "US".
res = streamlit_app._handle_scope_change("USD")
expect("first-render returns False (no reset)", res is False)
expect("first-render seeds cc_country to US for USD scope",
       _streamlit.session_state.get("cc_country") == "US",
       f"got {_streamlit.session_state.get('cc_country')!r}")
expect("first-render records _prev_scope",
       _streamlit.session_state.get("_prev_scope") == "USD")

# Subsequent first-render with same scope is idempotent.
res2 = streamlit_app._handle_scope_change("USD")
expect("same-scope second call returns False", res2 is False)
expect("cc_country still US", _streamlit.session_state.get("cc_country") == "US")

# If the user already picked a country, first-render must NOT clobber it.
for k in list(_streamlit.session_state.keys()):
    del _streamlit.session_state[k]
_streamlit.session_state["cc_country"] = "Brazil"
streamlit_app._handle_scope_change("USD")
expect("first-render preserves user-chosen cc_country",
       _streamlit.session_state.get("cc_country") == "Brazil",
       f"got {_streamlit.session_state.get('cc_country')!r}")

# EUR -> Eurozone (regional override)
for k in list(_streamlit.session_state.keys()):
    del _streamlit.session_state[k]
streamlit_app._handle_scope_change("EUR")
expect("EUR seeds cc_country to Eurozone",
       _streamlit.session_state.get("cc_country") == "Eurozone",
       f"got {_streamlit.session_state.get('cc_country')!r}")

# GBP -> UK
for k in list(_streamlit.session_state.keys()):
    del _streamlit.session_state[k]
streamlit_app._handle_scope_change("GBP")
expect("GBP seeds cc_country to UK",
       _streamlit.session_state.get("cc_country") == "UK")

# PM scope -> no seed (default_catalogue_country returns None)
for k in list(_streamlit.session_state.keys()):
    del _streamlit.session_state[k]
streamlit_app._handle_scope_change("WEEKPM")
expect("WEEKPM does NOT seed cc_country (no representative country)",
       "cc_country" not in _streamlit.session_state,
       f"got {_streamlit.session_state.get('cc_country')!r}")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
