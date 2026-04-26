"""Regression tests for tasks #44-#48:

- Macro Notes tab parses note files into version blocks ordered by end-date desc.
- _macro_note_versions returns (block, label, start, end, idx) tuples and is
  stable when windows are equal or absent.
- tab_macro_notes accepts a single `state` dict argument and uses sidebar scope
  to pick the default file.
- Weekly Monitor week selector defaults to "All weeks" (index 0).
- streamlit_app imports cleanly with the new signature.
"""
import sys, datetime as _dt, inspect, re
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
# 1. streamlit_app imports cleanly and exposes the new helpers.
# ---------------------------------------------------------------------------
import streamlit_app  # noqa: E402
from core.parsers import Block, extract_blocks, block_data_window  # noqa: E402

expect("streamlit_app imports", True)
expect("_macro_note_versions is callable",
       callable(getattr(streamlit_app, "_macro_note_versions", None)))
expect("tab_macro_notes is callable",
       callable(getattr(streamlit_app, "tab_macro_notes", None)))

sig = inspect.signature(streamlit_app.tab_macro_notes)
params = list(sig.parameters.keys())
expect("tab_macro_notes takes (state) - one param",
       len(params) == 1 and params[0] == "state",
       f"got params={params}")

views = getattr(streamlit_app, "_MACRO_NOTE_VIEWS", None)
expect("_MACRO_NOTE_VIEWS exposes 3 modes",
       isinstance(views, list) and len(views) == 3,
       repr(views))
expect("_MACRO_NOTE_VIEWS first option = Latest only",
       views and views[0] == "Latest note only",
       repr(views))


# ---------------------------------------------------------------------------
# 2. _macro_note_versions sorts by end-date desc with stable tie-break and
#    sinks window-less blocks to the bottom.
# ---------------------------------------------------------------------------
def _block(stem, txt, dw=None, dws=None, dwe=None):
    return Block(
        stem=stem,
        source_file="USD_MACRO_NOTE.txt",
        raw_text=txt,
        data_window=dw,
        data_window_start=dws,
        data_window_end=dwe,
    )

b_apr = _block("USD_MACRO_NOTE", "Apr 2026 note body", dw="13 Apr 2026 to 17 Apr 2026",
               dws="13 Apr 2026", dwe="17 Apr 2026")
b_mar = _block("USD_MACRO_NOTE", "Mar 2026 note body", dw="9 Mar 2026 to 13 Mar 2026",
               dws="9 Mar 2026",  dwe="13 Mar 2026")
b_feb = _block("USD_MACRO_NOTE", "Feb 2026 note body", dw="2 Feb 2026 to 6 Feb 2026",
               dws="2 Feb 2026",  dwe="6 Feb 2026")
b_nowin = _block("USD_MACRO_NOTE", "No window note - just prose")

versions = streamlit_app._macro_note_versions([b_feb, b_apr, b_nowin, b_mar])
expect("returns 4 entries", len(versions) == 4, f"got {len(versions)}")

# tuple shape
expect("entries are 5-tuples", all(len(t) == 5 for t in versions))
v0_block, v0_label, v0_start, v0_end, v0_idx = versions[0]
expect("first entry is the Apr block (latest end)",
       v0_block is b_apr, f"got block with text={v0_block.raw_text!r}")
expect("first entry end is 2026-04-17",
       v0_end == _dt.date(2026, 4, 17), repr(v0_end))

ends = [t[3] for t in versions]
expect("Apr first, Mar second, Feb third",
       (ends[0] == _dt.date(2026, 4, 17)
        and ends[1] == _dt.date(2026, 3, 13)
        and ends[2] == _dt.date(2026, 2, 6)),
       repr(ends))

# window-less block must be last
expect("window-less block sinks to the bottom",
       versions[-1][0] is b_nowin,
       f"got {versions[-1][0].raw_text!r}")


# ---------------------------------------------------------------------------
# 3. End-to-end: a marker-delimited file with two Data window blocks parses
#    into two versions and the most recent wins.
# ---------------------------------------------------------------------------
TWO_NOTES = """\
<<USD_MACRO_NOTE_BEGIN>>

USD Macro Note

Data window: 13 Apr 2026 to 17 Apr 2026

The Fed's stance hardened this week...

Data window: 9 Mar 2026 to 13 Mar 2026

Earlier note - softer tone, growth concerns dominant.

<<USD_MACRO_NOTE_END>>
"""

blocks = extract_blocks(TWO_NOTES, source_file="USD_MACRO_NOTE.txt")
expect("two blocks parsed from marker file", len(blocks) == 2, f"got {len(blocks)}")
versions2 = streamlit_app._macro_note_versions(blocks)
expect("two versions", len(versions2) == 2, f"got {len(versions2)}")
latest_block, latest_label, _, latest_end, _ = versions2[0]
expect("latest version end-date = 2026-04-17",
       latest_end == _dt.date(2026, 4, 17), repr(latest_end))
expect("latest body mentions the Fed",
       "Fed" in latest_block.raw_text, repr(latest_block.raw_text[:80]))


# ---------------------------------------------------------------------------
# 4. Empty input returns empty list cleanly (no crash).
# ---------------------------------------------------------------------------
expect("empty list -> empty versions", streamlit_app._macro_note_versions([]) == [])


# ---------------------------------------------------------------------------
# 5. Weekly Monitor default is "All weeks" (index=0). Source-level grep so we
#    catch a regression even if the widget returns are mocked away in tests.
# ---------------------------------------------------------------------------
src_path = _os.path.join(_REPO_ROOT, "streamlit_app.py")
with open(src_path, "r", encoding="utf-8") as fh:
    src = fh.read()
expect("Weekly week selector uses index=0 default",
       'index=0,  # default = "All weeks"' in src,
       "missing 'index=0' default-marker in streamlit_app.py")
expect("Weekly week selector NOT defaulting to index=1",
       not re.search(r'index\s*=\s*1,\s*#\s*default\s*=\s*"All weeks"', src),
       "found a stray index=1 'All weeks' default")


# ---------------------------------------------------------------------------
# 6. Macro Notes scope-aware default: file list ordering uses ALL_SCOPES so
#    USD_MACRO_NOTE.txt is the first option for sidebar scope = "USD".
#    We exercise the same option-build logic here without spinning up
#    Streamlit, so the default index is reproducible.
# ---------------------------------------------------------------------------
from core.config import ALL_SCOPES, SCOPE_FILES  # noqa: E402

note_options = [
    (scope, SCOPE_FILES[scope]["macro_note"])
    for scope in ALL_SCOPES
    if SCOPE_FILES[scope].get("macro_note")
]
expect("at least one macro-note scope is configured", len(note_options) >= 1)

usd_idx = next((i for i, (s, _) in enumerate(note_options) if s == "USD"), -1)
expect("USD has a macro-note file mapping", usd_idx >= 0,
       f"note_options={note_options}")
expect("USD file is USD_MACRO_NOTE.txt",
       note_options[usd_idx][1] == "USD_MACRO_NOTE.txt",
       repr(note_options[usd_idx]))

# Mimic the lookup the tab does to decide the default selection.
def _default_idx(state):
    sidebar_scope = (state or {}).get("scope", "")
    for i, (s, _) in enumerate(note_options):
        if s == sidebar_scope:
            return i
    return 0

expect("scope=USD picks USD index", _default_idx({"scope": "USD"}) == usd_idx)
expect("scope=missing falls back to 0", _default_idx({"scope": "ZZZ"}) == 0)
expect("empty state falls back to 0", _default_idx({}) == 0)
expect("None state falls back to 0", _default_idx(None) == 0)


# ---------------------------------------------------------------------------
# 7. Header text appears once at the top of the tab body, never per-block.
#    Source-level check that "File:" caption is bound to a single st.caption
#    call in tab_macro_notes (not inside a per-version loop).
# ---------------------------------------------------------------------------
tab_src = inspect.getsource(streamlit_app.tab_macro_notes)
file_caption_count = tab_src.count("File: `")
expect("tab_macro_notes builds the File header exactly once",
       file_caption_count == 1, f"got count={file_caption_count}")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
