"""Regression tests for the Macro Synthesis tab (tasks #75-#77).

Locks the contract:
  - core.parsers.split_top_level_sections splits a weekly block by
    `A. ...`, `B. ...`, `C. ...`, `D. ...` headers and returns ordered
    (letter, header, body) tuples.
  - tab_macro_synthesis exists, accepts a single `state` argument, and
    is wired into main()'s tab list.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.parsers import split_top_level_sections

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
# 1. split_top_level_sections happy path -- A/B/C order preserved.
# ---------------------------------------------------------------------------
TEXT = """\
DATA WINDOW: 23 Mar 2026 to 27 Mar 2026

A. US WEEK \u2014 MACRO SYNTHESIS
The week resolved into a clearer inflation-constrained, stagflation-risk configuration.
The decisive weekly shift came from the inflation and expectations side.

B. US MACRO SIGNAL SCOREBOARD

Growth: ~
Supporting evidence:
The week's growth signal stayed mixed.

Labor: ~
Supporting evidence:
Hard labor data remained resilient.

Inflation: -
Supporting evidence:
Unit labor costs were revised up.

C. FULL RELEASE ARCHIVE
UNITED STATES \u2014 National Activity Index (Feb)
Release Date: 23 Mar 2026
Importance: **
"""

sections = split_top_level_sections(TEXT)
expect("three sections (A/B/C) parsed",
       len(sections) == 3, f"got {len(sections)}")

letters = [L for L, _h, _b in sections]
expect("section order is [A, B, C]",
       letters == ["A", "B", "C"], f"got {letters}")

a_letter, a_header, a_body = sections[0]
b_letter, b_header, b_body = sections[1]
c_letter, c_header, c_body = sections[2]

expect("A header preserved",
       a_header == "A. US WEEK \u2014 MACRO SYNTHESIS",
       f"got {a_header!r}")
expect("B header preserved",
       b_header == "B. US MACRO SIGNAL SCOREBOARD",
       f"got {b_header!r}")
expect("C header preserved",
       c_header == "C. FULL RELEASE ARCHIVE",
       f"got {c_header!r}")

# Bodies don't contain the next section's header.
expect("A body does NOT contain B header",
       "B. US MACRO SIGNAL" not in a_body,
       "section A leaked into B's territory")
expect("A body does NOT contain C header",
       "C. FULL RELEASE" not in a_body)
expect("B body does NOT contain C header",
       "C. FULL RELEASE" not in b_body)

# Body content sanity.
expect("A body has the synthesis prose",
       "stagflation-risk configuration" in a_body)
expect("B body has the scoreboard rows",
       "Growth: ~" in b_body and "Inflation: -" in b_body)
expect("C body has the release entry",
       "National Activity Index" in c_body)

# Header lines themselves are NOT in the body (only the prose after).
expect("A body does NOT include its own header",
       "A. US WEEK" not in a_body)


# ---------------------------------------------------------------------------
# 2. Edge cases: single section, no sections, leading prose before A, only D.
# ---------------------------------------------------------------------------
expect("empty text -> []",
       split_top_level_sections("") == [])
expect("None -> []",
       split_top_level_sections(None) == [])

# Leading prose before the first section header is dropped (no-letter prose
# isn't a section).
LEADING = """\
some preamble prose
that has no section letter

A. SECTION ALPHA
body of A
"""
sec = split_top_level_sections(LEADING)
expect("leading prose dropped, only A returned",
       len(sec) == 1 and sec[0][0] == "A",
       f"got {sec}")
expect("A body of single-section text",
       sec[0][2] == "body of A",
       f"got {sec[0][2]!r}")

# Only D.
ONLY_D = "D. SUMMARY ARCHIVE\nfinal summary content"
sec_d = split_top_level_sections(ONLY_D)
expect("only D parsed",
       len(sec_d) == 1 and sec_d[0][0] == "D")


# ---------------------------------------------------------------------------
# 3. Multi-letter false-positives must NOT be treated as section headers.
# ---------------------------------------------------------------------------
NOT_SECTIONS = """\
A. SECTION ALPHA
prose for A.
Q4. revisions came in hot.
14. fourteenth item.
e. lowercase letter.
AA. double-letter prefix.
B. SECTION BETA
prose for B.
"""
sec2 = split_top_level_sections(NOT_SECTIONS)
expect("only A and B parsed (Q4/14/e/AA ignored)",
       len(sec2) == 2 and [s[0] for s in sec2] == ["A", "B"],
       f"got {[s[0] for s in sec2]}")
expect("A body retains the Q4/14/e/AA noise lines",
       "Q4. revisions" in sec2[0][2]
       and "14. fourteenth" in sec2[0][2]
       and "e. lowercase" in sec2[0][2]
       and "AA. double-letter" in sec2[0][2])


# ---------------------------------------------------------------------------
# 4. tab_macro_synthesis exists, takes a `state` param, and is wired into
#    main() between Weekly Monitor and Macro Notes.
# ---------------------------------------------------------------------------
import inspect, streamlit_app  # noqa: E402

expect("tab_macro_synthesis is callable",
       callable(getattr(streamlit_app, "tab_macro_synthesis", None)))

sig = inspect.signature(streamlit_app.tab_macro_synthesis)
params = list(sig.parameters.keys())
expect("tab_macro_synthesis takes (state)",
       params == ["state"], f"got params={params}")

main_src = inspect.getsource(streamlit_app.main)
expect("main() builds 4 tabs",
       "tab1, tab2, tab3, tab4" in main_src,
       "tab count not updated to 4")
expect("Macro Synthesis label present in main()",
       '"Macro Synthesis"' in main_src,
       "tab list missing 'Macro Synthesis' label")
expect("main() calls tab_macro_synthesis",
       "tab_macro_synthesis(state)" in main_src,
       "tab_macro_synthesis not wired into main()")

# Tab order: Weekly Monitor, Macro Synthesis, Macro Notes, Catalogue.
i_weekly = main_src.find('"Weekly Monitor"')
i_synth = main_src.find('"Macro Synthesis"')
i_notes = main_src.find('"Macro Notes"')
i_cat = main_src.find('"Country Release Catalogue"')
expect("tab order is Weekly -> Synthesis -> Notes -> Catalogue",
       0 < i_weekly < i_synth < i_notes < i_cat,
       f"got positions weekly={i_weekly}, synth={i_synth}, notes={i_notes}, cat={i_cat}")


# ---------------------------------------------------------------------------
# 5. tab_macro_notes splits a macro-note file into one block per VERSION via
#    extract_macro_note_versions. The old extract_blocks(split_weekly=True)
#    path merged every <<BEGIN>>/<<END>> pair and re-split at each
#    "Data window:" line, so "Latest note only" bled the next version's
#    markers and body into the view. The version splitter fixes that.
# ---------------------------------------------------------------------------
notes_src = inspect.getsource(streamlit_app.tab_macro_notes)
expect("tab_macro_notes uses extract_macro_note_versions",
       "extract_macro_note_versions(result.text" in notes_src,
       "tab_macro_notes no longer wires in the version splitter")
expect("tab_macro_notes does NOT re-fragment via plain extract_blocks",
       "extract_blocks(result.text" not in notes_src,
       "tab_macro_notes still uses the fragmenting extract_blocks path")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
