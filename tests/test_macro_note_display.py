"""Macro Notes tab: presentation-only rendering of a note version.

Scope of the change under test (and nothing else): the tab used to dump each
note into one grey `st.code()` box, discarding the note's own Markdown
hierarchy. It now renders Markdown, shows the note's own H1 title, and -- when
the note carries "# I. COMPRESSED NOTE" -- shows that PM section first, then
the full note without repeating it.

Everything upstream (GitHub fetch, cache, version detection, ordering, the
three View options, expanders and labels) is unchanged; section 5 pins that.

The tab is exercised with EUR because it has a macro-note file configured.
CAD -- the reference note format -- has none in SCOPE_FILES, so the real CAD
note is pushed through the render helper directly in section 6.
"""
import inspect
import io
import os as _os
import sys

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st  # the stub, when run via run_tests.py  # noqa: E402

_STUB = getattr(st, "__version__", "").endswith("test-stub")

from core.config import SCOPE_FILES  # noqa: E402
from core.loaders import LoadResult  # noqa: E402
from core.parsers import extract_macro_note_versions  # noqa: E402
import streamlit_app  # noqa: E402

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


split = streamlit_app._split_compressed_note
strip_markers = streamlit_app._strip_macro_note_markers
has_h1 = streamlit_app._note_has_h1
split_head = streamlit_app._split_note_head
md = streamlit_app._markdown_for_display
HEADING_RE = streamlit_app._COMPRESSED_HEADING_RE


# ---------------------------------------------------------------------------
# Fixtures: a new-format note (shape of the Sept-2026 CAD note) and a legacy
# plain-text note (shape of every USD note). EUR markers so the parser's
# known-stem path splits them into two versions.
# ---------------------------------------------------------------------------
NEW_NOTE = """\
<<EUR_MACRO_NOTE_BEGIN>>

# EUR Macro Note - Euro area: Q2 Resilience, Softer Q3 Handoff

**As of date:** 9 September 2026
**Horizon:** 4-week impulse window -> 3-6 month euro area / EUR / ECB scenario update
Data window: 1 Sep 2026 to 9 Sep 2026

## 4-WEEK MACRO SIGNAL BOARD

**Growth:** ~ Strong Q2 reset / softer Q3 handoff
**Labor:** down Headcount recovery stalled

## Growth / Activity

Q2 GDP +3.3% annualized. Consumption carries the floor.

## Labor / Employment

August employment -41.7k; **** Labour Force Survey was the key print.

## Bottom Line

Stronger economy, softer momentum.

# I. COMPRESSED NOTE

**REGIME:** Moved from recession risk to **strong Q2 resilience**.
**EXECUTIVE:** Q2 GDP +3.3% annualized.
**GROWTH:** Consumption and investment carry the floor.
**BOTTOM LINE:** Stronger economy, softer momentum.
**BASE CASE:** **ECB hold; shallow Q3 slowdown.**

<<EUR_MACRO_NOTE_END>>
"""

LEGACY_NOTE = """\
<<EUR_MACRO_NOTE_BEGIN>>

EUR Macro Note - Euro area: Hold-With-Look-Through
As of date: 5 Jun 2026
Horizon: 4-week impulse window
Data window: 1 Jun 2026 to 5 Jun 2026

4-WEEK MACRO SIGNAL BOARD
Growth: ~
Labor: up

Executive Summary
The ECB held. Nothing in this note is Markdown.

<<EUR_MACRO_NOTE_END>>
"""


# ---------------------------------------------------------------------------
# 1. Marker stripping
# ---------------------------------------------------------------------------
stripped = strip_markers(NEW_NOTE)
expect("BEGIN marker removed", "<<EUR_MACRO_NOTE_BEGIN>>" not in stripped)
expect("END marker removed", "<<EUR_MACRO_NOTE_END>>" not in stripped)
expect("content untouched by marker stripping",
       "Q2 GDP +3.3% annualized" in stripped and "**REGIME:**" in stripped)
expect("triple-bracket markers also removed",
       "<<<" not in strip_markers("<<<USD_MACRO_NOTE_BEGIN>>>\nbody\n<<<USD_MACRO_NOTE_END>>>"))
expect("a marker-like token inside prose is left alone",
       strip_markers("see <<CAD_MACRO_NOTE_BEGIN>> in the file")
       == "see <<CAD_MACRO_NOTE_BEGIN>> in the file")
expect("no markers -> text unchanged", strip_markers("plain\ntext") == "plain\ntext")
expect("marker stripping is safe on empty / None",
       strip_markers("") == "" and strip_markers(None) == "")


# ---------------------------------------------------------------------------
# 2. _split_compressed_note is pure and narrow
# ---------------------------------------------------------------------------
full, comp = split(NEW_NOTE)
expect("compressed section detected", comp is not None)
expect("compressed body starts with its first field",
       (comp or "").startswith("**REGIME:**"), f"got {(comp or '')[:40]!r}")
expect("compressed body keeps every field",
       all(k in (comp or "") for k in ("**EXECUTIVE:**", "**GROWTH:**",
                                       "**BOTTOM LINE:**", "**BASE CASE:**")))
expect("compressed heading line itself is dropped from the body",
       "COMPRESSED NOTE" not in (comp or ""))
expect("full note ends before the compressed heading",
       "COMPRESSED NOTE" not in full and "**REGIME:**" not in full)
expect("full note keeps everything above it",
       "# EUR Macro Note" in full and "## Growth / Activity" in full
       and "Stronger economy, softer momentum." in full)
expect("full note ends cleanly at Bottom Line",
       full.rstrip().endswith("Stronger economy, softer momentum."), f"ends {full[-40:]!r}")
expect("markers are gone from both halves",
       "<<" not in full and "<<" not in (comp or ""))

# Tolerated variants: ## heading, extra whitespace, case.
for variant in ("## I. COMPRESSED NOTE", "#  I.  COMPRESSED   NOTE  ", "# i. compressed note"):
    f2, c2 = split("# Title\n\nbody\n\n" + variant + "\n\n**REGIME:** x\n")
    expect(f"variant {variant!r} splits",
           c2 is not None and "**REGIME:**" in c2 and "body" in f2,
           f"got full={f2!r} comp={c2!r}")

# Not fuzzy: these must NOT split.
for decoy in ("# II. COMPRESSED NOTE", "# I. COMPRESSED NOTES",
              "The compressed note says hold.", "I. COMPRESSED NOTE",
              "### I. COMPRESSED NOTE"):
    f3, c3 = split("# Title\n\nbody\n\n" + decoy + "\n\nmore\n")
    expect(f"decoy {decoy!r} does not split", c3 is None and "more" in f3, f"got comp={c3!r}")

f4, c4 = split(LEGACY_NOTE)
expect("legacy note -> (cleaned text, None)",
       c4 is None and "The ECB held." in f4 and "<<" not in f4)
expect("heading with empty body -> (full, '')",
       split("# T\n\nbody\n\n# I. COMPRESSED NOTE\n\n") == ("# T\n\nbody", ""))
expect("split is safe on empty / None", split("") == ("", None) and split(None) == ("", None))
expect("split does not mutate its input (pure)",
       NEW_NOTE.count("COMPRESSED NOTE") == 1 and "<<EUR_MACRO_NOTE_BEGIN>>" in NEW_NOTE)


# ---------------------------------------------------------------------------
# 3. Title / head detection and display markdown
# ---------------------------------------------------------------------------
expect("new-format note has an H1", has_h1(NEW_NOTE))
expect("legacy note has no H1", not has_h1(LEGACY_NOTE))
expect("## alone is not an H1", not has_h1("## Section\ntext"))
expect("'#1 risk' is not an H1", not has_h1("#1 risk\ntext"))

head, body = split_head(full)
expect("head holds the H1 and metadata",
       head.startswith("# EUR Macro Note") and "**As of date:**" in head
       and "**Horizon:**" in head)
expect("head stops before the first ## section", "## 4-WEEK" not in head)
expect("body starts at the first ## section", body.startswith("## 4-WEEK MACRO SIGNAL BOARD"))
expect("head + body is the whole note (nothing dropped)",
       (head + "\n\n" + body).replace("\n", "") == full.replace("\n", ""))
expect("no ## heading -> empty head, whole text as body",
       split_head("# T\nline") == ("", "# T\nline"))

out = md("As of: 5 Jun 2026\nHorizon: 4 weeks\n\nGrowth: ~")
expect("consecutive lines get hard breaks",
       "As of: 5 Jun 2026  \nHorizon: 4 weeks  " in out, f"got {out!r}")
expect("blank lines stay blank (paragraph breaks kept)", "\n\nGrowth: ~  " in out)
expect("bare **** flag is escaped for markdown",
       md("**** Labour Force Survey") == r"\*\*\*\* Labour Force Survey  ")
expect("**bold** pairs are untouched", md("**REGIME:** x") == "**REGIME:** x  ")
expect("display markdown is safe on empty / None", md("") == "" and md(None) == "")


# ---------------------------------------------------------------------------
# 4. End-to-end render through the tab (stub only)
# ---------------------------------------------------------------------------
if not _STUB:
    print("  SKIP - render checks need the offline stub; run via `py run_tests.py`")
    print(f"\n{PASS} ok, {FAIL} fail")
    sys.exit(0 if FAIL == 0 else 1)

OPTS = [(sc, SCOPE_FILES[sc]["macro_note"]) for sc in streamlit_app.ALL_SCOPES
        if SCOPE_FILES[sc].get("macro_note")]


def _picker_index(scope):
    return [i for i, (s, _f) in enumerate(OPTS) if s == scope][0]


SCOPE = "EUR"
NOTE_FILE = SCOPE_FILES[SCOPE]["macro_note"]
expect("EUR has a macro-note file configured (the tab fixture scope)",
       bool(NOTE_FILE), f"got {NOTE_FILE!r}")
# Legacy first in the file, new note second: ordering must come from the data
# windows (new = Sep, legacy = Jun), not from file position.
_text = LEGACY_NOTE + "\n" + NEW_NOTE
_file = NOTE_FILE


def _fake_load_file(filename):
    txt = _text if filename == _file else ""
    return LoadResult(filename=filename, text=txt, source="cache",
                      fetched_at=None, error=None)


streamlit_app._load_file = _fake_load_file


def render(scope, view):
    st.reset()
    st.set_widget_value("mn_select", _picker_index(scope))
    st.set_widget_value("mn_view_mode", view)
    streamlit_app.tab_macro_notes({"scope": scope, "view": "macro_note",
                                   "levels": [], "themes": [], "time_window": "All"})
    calls = st.calls()
    return {
        "md": [str(c[2][0]) for c in calls if c[1] == "markdown" and c[2]],
        "code": [str(c[2][0]) for c in calls if c[1] == "code" and c[2]],
        "captions": [str(c[2][0]) for c in calls if c[1] == "caption" and c[2]],
        "expanders": [str(c[2][0]) for c in calls if c[1] == "expander" and c[2]],
        "containers": [c[3] for c in calls if c[1] == "container"],
        "dividers": sum(1 for c in calls if c[1] == "divider"),
        "all_text": [str(c[2][0]) for c in calls if c[2]],
    }


def _first_index(items, needle):
    for i, s in enumerate(items):
        if needle in s:
            return i
    return -1


views = streamlit_app._MACRO_NOTE_VIEWS
expect("the three View options are unchanged",
       views == ["Latest note only", "Previous notes", "All notes archive"], f"got {views}")

# --- Latest note only: the new-format note ---
lat = render(SCOPE, views[0])
expect("latest view uses no st.code box for the note", lat["code"] == [],
       f"code calls: {len(lat['code'])}")
expect("the note's own rich H1 title is rendered",
       any("# EUR Macro Note - Euro area: Q2 Resilience" in m for m in lat["md"]))
expect("no synthetic '### EUR - Macro Note' on top of the real H1",
       not any(m.strip() == "### EUR - Macro Note" for m in lat["md"]),
       f"md={[m[:40] for m in lat['md'][:3]]}")
expect("As-of date and Horizon are rendered on their own lines",
       any("**As of date:** 9 September 2026  \n**Horizon:**" in m for m in lat["md"]))
i_pm = _first_index(lat["md"], "### PM COMPRESSED NOTE")
i_full = _first_index(lat["md"], "### Full Macro Note")
i_title = _first_index(lat["md"], "# EUR Macro Note")
i_regime = _first_index(lat["md"], "**REGIME:**")
i_growth = _first_index(lat["md"], "## Growth / Activity")
expect("PM COMPRESSED NOTE heading is present", i_pm >= 0)
expect("Full Macro Note heading is present", i_full >= 0)
expect("title comes before the compressed block", 0 <= i_title < i_pm, f"{i_title} vs {i_pm}")
expect("compressed block comes before the full note", i_pm < i_full, f"{i_pm} vs {i_full}")
expect("compressed fields sit inside the compressed block", i_pm < i_regime < i_full,
       f"pm={i_pm} regime={i_regime} full={i_full}")
expect("## sections follow the Full Macro Note heading", i_growth > i_full,
       f"growth={i_growth} full={i_full}")
expect("the compressed section is not repeated in the full note",
       sum(1 for m in lat["md"] if "**REGIME:**" in m) == 1)
expect("the '# I. COMPRESSED NOTE' heading is never rendered",
       not any(HEADING_RE.search(m) for m in lat["md"]))
expect("compressed block is a bordered container",
       any(kw.get("border") is True for kw in lat["containers"]),
       f"containers={lat['containers']}")
expect("'30-60 second read' caption present",
       any("second read" in c for c in lat["captions"]))
expect("one divider between compressed and full note", lat["dividers"] == 1,
       f"got {lat['dividers']}")
expect("wrapper markers are invisible everywhere",
       not any("<<" in s for s in lat["all_text"]))
expect("bare **** flag survives, escaped, inside the full note",
       any(r"\*\*\*\* Labour Force Survey" in m for m in lat["md"]))
expect("File header caption rendered exactly once",
       sum(1 for c in lat["captions"] if c.startswith("File: `")) == 1)
expect("hidden-versions hint unchanged",
       any("earlier version(s) hidden" in c for c in lat["captions"]))

# --- Previous notes: the legacy note inside its expander ---
prev = render(SCOPE, views[1])
expect("previous view keeps one expander with the same label format",
       prev["expanders"] == ["Data window: 1 Jun 2026 to 5 Jun 2026"],
       f"got {prev['expanders']}")
expect("previous view uses no st.code", prev["code"] == [])
expect("legacy note renders as markdown with its line breaks kept",
       any("As of date: 5 Jun 2026  \nHorizon: 4-week impulse window  " in m
           for m in prev["md"]),
       f"md={[m[:80] for m in prev['md']]}")
expect("legacy note gets no compressed block and no Full Macro Note heading",
       not any("PM COMPRESSED NOTE" in m or "Full Macro Note" in m for m in prev["md"]))
expect("legacy note gets no synthetic scope heading inside the expander",
       not any(m.strip() == "### EUR - Macro Note" for m in prev["md"]))
expect("markers invisible in previous view", not any("<<" in m for m in prev["md"]))

# --- All notes archive: both, same labels ---
arc = render(SCOPE, views[2])
expect("archive keeps two expanders, Latest then Previous, same labels",
       arc["expanders"] == ["Latest  -  Data window: 1 Sep 2026 to 9 Sep 2026",
                            "Previous  -  Data window: 1 Jun 2026 to 5 Jun 2026"],
       f"got {arc['expanders']}")
expect("archive uses no st.code", arc["code"] == [])
expect("archive renders the compressed block for the new note only",
       sum(1 for m in arc["md"] if "### PM COMPRESSED NOTE" in m) == 1)
expect("archive renders the legacy note body",
       any("The ECB held." in m for m in arc["md"]))

# --- Legacy note as the LATEST (a file with no new-format note at all) ---
_text = LEGACY_NOTE
lat_legacy = render(SCOPE, views[0])
expect("legacy-only file: synthetic scope heading is kept for the latest view",
       any(m.strip() == "### EUR - Macro Note" for m in lat_legacy["md"]),
       f"md={[m[:40] for m in lat_legacy['md'][:2]]}")
expect("legacy-only file: no compressed block invented",
       not any("PM COMPRESSED NOTE" in m for m in lat_legacy["md"]))
expect("legacy-only file: no st.code", lat_legacy["code"] == [])
_text = LEGACY_NOTE + "\n" + NEW_NOTE


# ---------------------------------------------------------------------------
# 5. Nothing upstream changed
# ---------------------------------------------------------------------------
tab_src = inspect.getsource(streamlit_app.tab_macro_notes)
expect("tab still calls extract_macro_note_versions", "extract_macro_note_versions(" in tab_src)
expect("tab still orders via _macro_note_versions", "_macro_note_versions(" in tab_src)
expect("tab still seeds the picker via _seed_macro_note_picker", "_seed_macro_note_picker(" in tab_src)
expect("tab still loads via _load_file", "_load_file(" in tab_src)
expect("tab no longer dumps the note through st.code", "st.code(" not in tab_src)
expect("session-state keys unchanged", '"mn_select"' in tab_src and '"mn_view_mode"' in tab_src)
expect("File header built exactly once (existing contract)", tab_src.count("File: `") == 1)
expect("render helper takes only the note text (no parser objects mutated)",
       list(inspect.signature(streamlit_app._render_macro_note_content).parameters) == ["text"])


# ---------------------------------------------------------------------------
# 6. Real archive smoke, when the cached notes are present locally
# ---------------------------------------------------------------------------
# 6a. The reference CAD note. CAD has no macro_note in SCOPE_FILES, so it
#     cannot be picked in the tab; push its compressed version straight
#     through the render helper, exactly as the tab would.
cad_path = _os.path.join(_REPO_ROOT, "data", "cache", "CAD_MACRO_NOTE.txt")
if not _os.path.exists(cad_path):
    print("  skip - CAD_MACRO_NOTE.txt not cached locally")
else:
    cad_text = io.open(cad_path, encoding="utf-8").read()
    blocks = extract_macro_note_versions(cad_text, source_file="CAD_MACRO_NOTE.txt")
    with_comp = [b for b in blocks if HEADING_RE.search(b.raw_text)]
    expect("real CAD archive has exactly one version carrying a compressed note",
           len(with_comp) == 1, f"got {len(with_comp)} of {len(blocks)}")
    if with_comp:
        st.reset()
        streamlit_app._render_macro_note_content(with_comp[0].raw_text)
        calls = st.calls()
        cmd = [str(c[2][0]) for c in calls if c[1] == "markdown" and c[2]]
        expect("real CAD: rendered without st.code",
               not any(c[1] == "code" for c in calls))
        expect("real CAD: rich H1 title rendered",
               any(m.startswith("# CAD Macro Note") and "Q2 Resilience" in m for m in cmd),
               f"first md={cmd[0][:80]!r}" if cmd else "no markdown")
        expect("real CAD: As-of date and Horizon on their own lines",
               any("**As of date:** 9 September 2026  \n**Horizon:**" in m for m in cmd))
        j_pm = _first_index(cmd, "### PM COMPRESSED NOTE")
        j_full = _first_index(cmd, "### Full Macro Note")
        j_reg = _first_index(cmd, "**REGIME:**")
        j_board = _first_index(cmd, "## 4-WEEK MACRO SIGNAL BOARD")
        expect("real CAD: compressed block before the full note", 0 <= j_pm < j_full)
        expect("real CAD: REGIME field inside the compressed block", j_pm < j_reg < j_full)
        expect("real CAD: all fifteen compressed fields present",
               all(f"**{k}:**" in cmd[j_reg] for k in (
                   "REGIME", "4-WEEK SIGNAL BOARD", "EXECUTIVE", "GROWTH", "LABOR",
                   "INFLATION", "BOC", "RATES / FX / FINANCIAL CONDITIONS",
                   "POLITICAL / POLICY", "5 KEY RELEASES / EVENTS", "ARC",
                   "TRIGGER MAP", "DEBATE / PUBLIC TAPE", "BOTTOM LINE", "BASE CASE")),
               "a compressed field is missing")
        expect("real CAD: ## sections follow the Full Macro Note heading", j_board > j_full)
        expect("real CAD: '# I. COMPRESSED NOTE' not repeated",
               not any(HEADING_RE.search(m) for m in cmd))
        expect("real CAD: compressed fields appear once only",
               sum(1 for m in cmd if "**REGIME:**" in m) == 1)
        expect("real CAD: no wrapper markers", not any("<<" in m for m in cmd))

# 6b. The real USD archive through the tab: every version is legacy.
usd_path = _os.path.join(_REPO_ROOT, "data", "cache", "USD_MACRO_NOTE.txt")
if not _os.path.exists(usd_path):
    print("  skip - USD_MACRO_NOTE.txt not cached locally")
else:
    _text = io.open(usd_path, encoding="utf-8").read()
    _file = SCOPE_FILES["USD"]["macro_note"]
    u_lat = render("USD", views[0])
    u_arc = render("USD", views[2])
    expect("real USD latest: no st.code", u_lat["code"] == [])
    expect("real USD latest: legacy title line rendered",
           any("Final PM Version" in m for m in u_lat["md"]))
    expect("real USD latest: metadata keeps its line breaks",
           any("As of: 30 Jun 2026  \n" in m for m in u_lat["md"]),
           f"md={[m[:70] for m in u_lat['md'][:2]]}")
    expect("real USD latest: synthetic scope heading kept for a legacy note",
           any(m.strip() == "### USD - Macro Note" for m in u_lat["md"]))
    expect("real USD: no compressed block invented",
           not any("PM COMPRESSED NOTE" in m for m in u_lat["md"] + u_arc["md"]))
    expect("real USD archive: all seven versions, same labels, no st.code",
           len(u_arc["expanders"]) == 7 and u_arc["code"] == []
           and u_arc["expanders"][0].startswith("Latest  -  "),
           f"expanders={len(u_arc['expanders'])}")
    expect("real USD: no wrapper markers",
           not any("<<" in m for m in u_lat["md"] + u_arc["md"]))


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
