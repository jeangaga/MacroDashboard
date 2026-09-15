"""Tests for the WEEK RECAP tab.

The landing tile: section I (COMPRESSED WEEK NOTE) for the most recent weeks,
laid out in a row, two weeks by default and widenable.

Covers the ordering/choice helpers directly, then renders the tab end-to-end
against the offline streamlit stub with `_load_file` monkeypatched, so the
column layout and week ordering are checked as actually drawn.
"""
import sys
import datetime as _dt
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st  # the stub, when run via run_tests.py  # noqa: E402

_STUB = getattr(st, "__version__", "").endswith("test-stub")

from core.loaders import LoadResult  # noqa: E402
from core.config import SCOPE_FILES  # noqa: E402
from core.parsers import Block, extract_blocks  # noqa: E402
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


def _week(stem, window, start, end, body_marker, with_note=True):
    """One <<STEM_BEGIN>>..<<STEM_END>> week, optionally carrying a section I."""
    tail = ""
    if with_note:
        tail = (
            "\nI. COMPRESSED WEEK NOTE\n\n"
            "### Regime\n"
            f"{body_marker} regime line.\n\n"
            "### Major Release Tape\n"
            f"**** US - CPI ({body_marker})\n"
        )
    return (
        f"<<{stem}_BEGIN>>\n"
        f"DATA WINDOW: {window}\n\n"
        f"A. USD WEEK - MACRO SYNTHESIS\n\n"
        f"{body_marker} synthesis prose.\n\n"
        f"C. FULL RELEASE ARCHIVE\n\n"
        f"United States - CPI ({body_marker})\n"
        f"Release Date: {start}\n"
        f"Importance: ****\n"
        f"1. Reuters Data\n"
        f"CPI YY: 2.6%\n"
        f"{tail}"
        f"<<{stem}_END>>\n"
    )


# Three new-format weeks (newest last in the file, to prove we sort) plus one
# older week with no section I.
THREE_WEEKS = (
    _week("USD_WEEK", "6 Jul 2026 to 10 Jul 2026", "8 Jul 2026", "10 Jul 2026", "JULY")
    + _week("USD_WEEK", "3 Aug 2026 to 7 Aug 2026", "5 Aug 2026", "7 Aug 2026", "AUGUST")
    + _week("USD_WEEK", "10 Aug 2026 to 14 Aug 2026", "12 Aug 2026", "14 Aug 2026", "LATEST")
    + _week("USD_WEEK", "1 Jun 2026 to 5 Jun 2026", "3 Jun 2026", "5 Jun 2026",
            "ANCIENT", with_note=False)
)

NO_NOTES = _week("USD_WEEK", "1 Jun 2026 to 5 Jun 2026", "3 Jun 2026",
                 "5 Jun 2026", "ANCIENT", with_note=False)


# ---------------------------------------------------------------------------
# 1. _recap_entries: newest first, window-less blocks last, body populated
# ---------------------------------------------------------------------------
blocks = extract_blocks(THREE_WEEKS, source_file="USD_WEEK.txt")
entries = streamlit_app._recap_entries(blocks)

expect("all four weeks returned", len(entries) == 4, f"got {len(entries)}")
markers = []
for e in entries:
    body = e["body"] or e["block"].raw_text
    markers.append(next((m for m in ("LATEST", "AUGUST", "JULY", "ANCIENT")
                         if m in body), "?"))
expect("weeks ordered newest-first",
       markers == ["LATEST", "AUGUST", "JULY", "ANCIENT"], f"got {markers}")
expect("newest entry carries its compressed body",
       "LATEST regime line" in entries[0]["body"])
expect("pre-A-I week has an empty body", entries[3]["body"] == "",
       f"got {entries[3]['body']!r}")
expect("entries expose the data-window label",
       "10 Aug 2026" in (entries[0]["label"] or ""), f"got {entries[0]['label']!r}")

# A block with no data window at all must sink, not crash.
nowin = Block(stem="USD_WEEK", source_file="USD_WEEK.txt",
              raw_text="I. COMPRESSED WEEK NOTE\n\n### Regime\nNo window.\n")
mixed = streamlit_app._recap_entries(list(blocks) + [nowin])
expect("window-less block sinks to the bottom",
       mixed[-1]["block"] is nowin,
       f"got {mixed[-1]['label']!r}")
expect("_recap_entries handles an empty list",
       streamlit_app._recap_entries([]) == [])
expect("_recap_entries handles None", streamlit_app._recap_entries(None) == [])


# ---------------------------------------------------------------------------
# 2. _recap_week_choices caps at what the file actually holds
# ---------------------------------------------------------------------------
expect("3 weeks available -> [1,2,3]",
       streamlit_app._recap_week_choices(3) == [1, 2, 3],
       f"got {streamlit_app._recap_week_choices(3)}")
expect("1 week available -> [1]",
       streamlit_app._recap_week_choices(1) == [1])
expect("5 weeks available -> [1,2,3,4,5]",
       streamlit_app._recap_week_choices(5) == [1, 2, 3, 4, 5],
       f"got {streamlit_app._recap_week_choices(5)}")
expect("8 weeks available -> the full option ladder",
       streamlit_app._recap_week_choices(8) == [1, 2, 3, 4, 6, 8],
       f"got {streamlit_app._recap_week_choices(8)}")
expect("0 weeks available -> no choices",
       streamlit_app._recap_week_choices(0) == [])
expect("default of 2 weeks is declared", streamlit_app._RECAP_DEFAULT_WEEKS == 2)


# ---------------------------------------------------------------------------
# 3. End-to-end render (stub only)
# ---------------------------------------------------------------------------
if not _STUB:
    print("  SKIP - render checks need the offline stub; run via `py run_tests.py`")
    print(f"\n{PASS} ok, {FAIL} fail")
    sys.exit(0 if FAIL == 0 else 1)

SCOPE = "USD"
SCOPE_FILE = SCOPE_FILES[SCOPE]["frozen_week"]
_text = THREE_WEEKS


def _fake_load_file(filename):
    if filename == SCOPE_FILE:
        return LoadResult(filename=filename, text=_text, source="cache",
                          fetched_at=None, error=None)
    return LoadResult(filename=filename, text="", source="cache",
                      fetched_at=None, error=None)


streamlit_app._load_file = _fake_load_file
STATE = {"scope": SCOPE, "view": "frozen_week", "levels": [], "themes": [],
         "time_window": "All"}


def render(weeks=None, raw=False, sections=None):
    st.reset()
    if weeks is not None:
        st.set_widget_value(f"wr_count_{SCOPE}", weeks)
    st.set_widget_value(f"wr_raw_{SCOPE}", raw)
    if sections is not None:
        st.set_widget_value(f"wr_sections_{SCOPE}", sections)
    streamlit_app.tab_week_recap(STATE)
    md = [str(c[2][0]) for c in st.calls(method="markdown") if c[2]]
    code = [str(c[2][0]) for c in st.calls(method="code") if c[2]]
    return {
        # Weeks stack vertically now, so the ONLY columns() call should be the
        # control row, columns([2, 3]). Any int spec would mean a side-by-side
        # week layout came back.
        "columns": [c[2][0] for c in st.calls(method="columns")
                    if isinstance(c[2][0], int)],
        "code": code,
        "markdown": md,
        # Week headers are single-line "### <data window>"; bodies are
        # multi-line. That split holds in both render modes.
        "labels": [m for m in md if "\n" not in m],
        "notes": code if raw else [m for m in md if "\n" in m],
        "dividers": len(st.calls(method="divider")),
        "info": [str(c[2][0]) for c in st.calls(method="info") if c[2]],
    }


expect("USD_WEEK.txt is the file the recap reads",
       SCOPE_FILE == "USD_WEEK.txt", f"got {SCOPE_FILE!r}")

# --- default: two weeks in one row ---
out = render()
expect("weeks are stacked, never side by side", out["columns"] == [],
       f"a side-by-side week layout came back: {out['columns']}")
expect("default shows the two newest notes",
       len(out["notes"]) == 2, f"got {len(out['notes'])} notes")
expect("one divider between the two weeks", out["dividers"] == 1,
       f"got {out['dividers']}")
expect("newest week is on top",
       "LATEST regime line" in out["notes"][0], f"got {out['notes'][0][:60]!r}")
expect("the week below it is the next one back (decreasing order)",
       "AUGUST regime line" in out["notes"][1], f"got {out['notes'][1][:60]!r}")
expect("older weeks are not rendered by default",
       not any("JULY" in c for c in out["notes"]))
expect("each week carries a '## <data window>' header",
       out["labels"] == ["## 10 Aug 2026 to 14 Aug 2026",
                         "## 3 Aug 2026 to 7 Aug 2026"],
       f"labels={out['labels']}")
expect("week header outranks the note's own ### subsections",
       all(m.startswith("## ") and not m.startswith("### ")
           for m in out["labels"]),
       f"labels={out['labels']}")
expect("the pre-A-I week is reported as skipped, not silently dropped",
       any("no compressed note" in c for c in
           [str(x[2][0]) for x in st.calls(method="caption") if x[2]]),
       "no caption explaining the skipped week")

# --- one week ---
out1 = render(1)
expect("1 week -> only the newest note",
       len(out1["notes"]) == 1 and "LATEST" in out1["notes"][0])
expect("1 week -> no divider", out1["dividers"] == 0, f"got {out1['dividers']}")

# --- three weeks, still stacked ---
out3 = render(3)
expect("3 weeks stay stacked", out3["columns"] == [], f"got {out3['columns']}")
expect("3 weeks -> two dividers", out3["dividers"] == 2, f"got {out3['dividers']}")
expect("3 weeks -> three notes, newest first",
       [("LATEST" in c, "AUGUST" in c, "JULY" in c) for c in out3["notes"]]
       == [(True, False, False), (False, True, False), (False, False, True)],
       f"got {[c[:40] for c in out3['notes']]}")

# --- importance flags survive both render modes ---
# Rendered mode escapes the bare flag so markdown prints it literally instead
# of consuming it as an unmatched emphasis run.
expect("rendered mode escapes the bare importance flag",
       any(r"\*\*\*\* US - CPI" in c for c in out3["notes"]),
       f"got {[c[:80] for c in out3['notes']]}")
expect("rendered mode keeps the ### subsection headings",
       all("### Regime" in c for c in out3["notes"]))

out_raw = render(3, raw=True)
expect("raw mode sends bodies to st.code, not st.markdown",
       len(out_raw["code"]) == 3
       and not [m for m in out_raw["markdown"] if "\n" in m],
       f"code={len(out_raw['code'])} "
       f"multiline-markdown={len([m for m in out_raw['markdown'] if chr(10) in m])}")
expect("raw mode is byte-verbatim (flag unescaped)",
       any("**** US - CPI" in c for c in out_raw["notes"])
       and not any("\\*" in c for c in out_raw["notes"]),
       f"got {[c[:80] for c in out_raw['notes']]}")

# The escaper itself: flags escaped, real markdown untouched.
esc = streamlit_app._escape_importance_flags
expect("escaper escapes a standalone ****", esc("**** US - CPI") == r"\*\*\*\* US - CPI",
       f"got {esc('**** US - CPI')!r}")
expect("escaper escapes a standalone ***", esc("*** CPI") == r"\*\*\* CPI")
expect("escaper leaves bold pairs alone",
       esc("* **Growth:** ~") == "* **Growth:** ~",
       f"got {esc('* **Growth:** ~')!r}")
expect("escaper leaves bullets alone",
       esc("* item one") == "* item one")
expect("escaper leaves headings alone",
       esc("### Regime") == "### Regime")
expect("escaper handles the real-world mixed line",
       esc("* **** **Employment Situation** - NFP")
       == r"* \*\*\*\* **Employment Situation** - NFP",
       f"got {esc('* **** **Employment Situation** - NFP')!r}")
expect("escaper is safe on empty input",
       esc("") == "" and esc(None) is None)

# --- many weeks stay stacked, no wrapping/columns at any count ---
# THREE_WEEKS holds 3 notes (plus one pre-A-I week); add two more so there are
# 5 compressed notes and the 4-per-row cap actually has something to wrap.
many = (THREE_WEEKS
        + _week("USD_WEEK", "18 May 2026 to 22 May 2026",
                "20 May 2026", "22 May 2026", "MAYWEEK")
        + _week("USD_WEEK", "20 Apr 2026 to 24 Apr 2026",
                "22 Apr 2026", "24 Apr 2026", "APRWEEK"))
_text = many
out5 = render(5)
expect("5 weeks are still stacked, not wrapped into columns",
       out5["columns"] == [], f"got {out5['columns']}")
expect("5 weeks -> five notes rendered", len(out5["notes"]) == 5,
       f"got {len(out5['notes'])}")
expect("5 weeks -> four dividers", out5["dividers"] == 4, f"got {out5['dividers']}")
expect("5 weeks stay in decreasing order",
       [next(m for m in ("LATEST", "AUGUST", "JULY", "MAYWEEK", "APRWEEK")
             if m in c) for c in out5["notes"]]
       == ["LATEST", "AUGUST", "JULY", "MAYWEEK", "APRWEEK"],
       f"got {[c[:30] for c in out5['notes']]}")
_text = THREE_WEEKS


# --- a file with no compressed notes at all explains itself ---
_text = NO_NOTES
out_none = render()
expect("file with no section I shows an explanation",
       any("No compressed week note" in i for i in out_none["info"]),
       f"infos={out_none['info']}")
expect("file with no section I renders nothing else",
       out_none["notes"] == [] and out_none["dividers"] == 0,
       f"notes={len(out_none['notes'])} dividers={out_none['dividers']}")
_text = THREE_WEEKS


# ---------------------------------------------------------------------------
# 3b. Subsection picker: all parts by default, narrowable
# ---------------------------------------------------------------------------
titles = streamlit_app._recap_subsection_titles(
    [e for e in streamlit_app._recap_entries(
        extract_blocks(THREE_WEEKS, source_file="USD_WEEK.txt")) if e["body"]]
)
expect("subsection titles collected in document order",
       titles == ["Regime", "Major Release Tape"], f"got {titles}")
expect("_recap_subsection_titles is safe on empty input",
       streamlit_app._recap_subsection_titles([]) == []
       and streamlit_app._recap_subsection_titles(None) == [])

out_all = render()
expect("default shows every part of the note",
       all("### Regime" in c and "### Major Release Tape" in c
           for c in out_all["notes"]),
       "a part was missing from the default view")

out_one = render(sections=["Regime"])
expect("narrowing to one part keeps it",
       all("### Regime" in c for c in out_one["notes"]),
       f"got {[c[:60] for c in out_one['notes']]}")
expect("narrowing to one part drops the others",
       not any("Major Release Tape" in c for c in out_one["notes"]),
       "an unselected part was still rendered")
expect("narrowing still shows every selected week",
       len(out_one["notes"]) == 2, f"got {len(out_one['notes'])}")

out_empty = render(sections=[])
expect("selecting nothing explains itself",
       any("Select at least one part" in i for i in out_empty["info"]),
       f"infos={out_empty['info']}")
expect("selecting nothing renders no notes", out_empty["notes"] == [])

# A week that lacks the selected part says so rather than rendering blank.
_text = (
    _week("USD_WEEK", "10 Aug 2026 to 14 Aug 2026", "12 Aug 2026", "14 Aug 2026",
          "LATEST")
    + "<<USD_WEEK_BEGIN>>\nDATA WINDOW: 3 Aug 2026 to 7 Aug 2026\n\n"
      "A. USD WEEK - MACRO SYNTHESIS\n\nOlder prose.\n\n"
      "I. COMPRESSED WEEK NOTE\n\n### Regime\n\nOnly a regime line.\n\n"
      "<<USD_WEEK_END>>\n"
)
out_partial = render(sections=["Major Release Tape"])
caps = [str(c[2][0]) for c in st.calls(method="caption") if c[2]]
expect("the week that has the part still renders it",
       any("Major Release Tape" in c for c in out_partial["notes"]),
       f"got {[c[:60] for c in out_partial['notes']]}")
expect("the week missing that part says so",
       any("None of the selected parts" in c for c in caps),
       f"captions={caps}")
_text = THREE_WEEKS

# The seeder: defaults to all, prunes stale values, never strands the user.
seed = streamlit_app._seed_recap_sections
sess = {}
seed(sess, "wr_sections_USD", ["Regime", "Scoreboard"])
expect("seeder selects everything on first render",
       sess["wr_sections_USD"] == ["Regime", "Scoreboard"],
       f"got {sess['wr_sections_USD']}")
sess["wr_sections_USD"] = ["Regime"]
seed(sess, "wr_sections_USD", ["Regime", "Scoreboard"])
expect("seeder leaves a manual narrowing alone",
       sess["wr_sections_USD"] == ["Regime"], f"got {sess['wr_sections_USD']}")
sess["wr_sections_USD"] = ["Regime", "Gone"]
seed(sess, "wr_sections_USD", ["Regime", "Scoreboard"])
expect("seeder prunes titles that no longer exist",
       sess["wr_sections_USD"] == ["Regime"], f"got {sess['wr_sections_USD']}")
sess["wr_sections_USD"] = ["Gone"]
seed(sess, "wr_sections_USD", ["Regime", "Scoreboard"])
expect("a selection pruned to nothing falls back to all",
       sess["wr_sections_USD"] == ["Regime", "Scoreboard"],
       f"got {sess['wr_sections_USD']}")


# ---------------------------------------------------------------------------
# 4. Week Recap is wired in as the FIRST tab
# ---------------------------------------------------------------------------
import inspect  # noqa: E402

main_src = inspect.getsource(streamlit_app.main)
expect("main() renders a Week Recap tab", '"Week Recap"' in main_src)
expect("Week Recap is the first tab",
       main_src.index('"Week Recap"') < main_src.index('"Weekly Monitor"'),
       "Week Recap is not first in st.tabs()")
expect("main() calls tab_week_recap", "tab_week_recap(state)" in main_src)
expect("scope change still runs before the tabs",
       main_src.find("_handle_scope_change") < main_src.find("st.tabs("))


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
