"""End-to-end render test for the Weekly Monitor's four note views.

The A-I work restructured `tab_weekly_monitor`'s per-week loop. The section
parsing is covered by test_week_sections_ai.py; this suite covers the thing
unit tests miss -- that the tab actually *runs*, and that each view renders the
sections it promises and none of the ones it doesn't.

Uses the offline streamlit stub (see tests/_stubs/streamlit.py), which records
every display call instead of drawing. Network is stubbed out too, so this is
fully offline.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st  # the stub, when run via run_tests.py  # noqa: E402

if not getattr(st, "__version__", "").endswith("test-stub"):
    print("  SKIP - needs the offline streamlit stub; run via `py run_tests.py`")
    print("\n0 ok, 0 fail")
    sys.exit(0)

from core.loaders import LoadResult  # noqa: E402
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


NEW_FORMAT = """\
<<ZAR_WEEK_BEGIN>>
DATA WINDOW: 3 Aug 2026 to 14 Aug 2026

A. ZAR WEEK - MACRO SYNTHESIS

The rand traded on a policy-constrained footing.

B. ZAR MACRO SIGNAL SCOREBOARD

Growth: -
Inflation: +

C. FULL RELEASE ARCHIVE

South Africa - CPI (Jul)
Release Date: 12 Aug 2026 | Local Time: 10:00
Importance: ****
1. Reuters Data
CPI YY: 4.6% | Prior: 4.4%

D. CENTRAL BANK TAPE

Summary - Policy reaction function
SARB stayed hawkish.

E. SIGNAL TENSION CHECK

Hard and survey data disagree.

F. 5 KEY RELEASES TO DIG INTO

1. South Africa CPI (Jul).

G. RED TEAM QUESTIONS

What if CPI is revised down?

H. CURRENCY MARKET-CONSENSUS SCAN

### Bottom line
Mildly bearish ZAR.

I. COMPRESSED WEEK NOTE

### Regime
Policy-constrained.

<<ZAR_WEEK_END>>
"""

SCOPE, VIEW = "ZAR", "frozen_week"
VIEW_KEY = f"wm_note_view_{SCOPE}_{VIEW}"

_scope_file = None


def _fake_load_file(filename):
    """Serve the fixture for the scope's own file; nothing for anything else.

    The tab also probes the regional bucket file (EM_WEEK.txt for ZAR) looking
    for newer weeks; returning an empty result keeps that path inert.
    """
    if filename == _scope_file:
        return LoadResult(filename=filename, text=NEW_FORMAT, source="cache",
                          fetched_at=None, error=None)
    return LoadResult(filename=filename, text="", source="cache",
                      fetched_at=None, error=None)


from core.config import SCOPE_FILES  # noqa: E402
_scope_file = SCOPE_FILES[SCOPE][VIEW]
streamlit_app._load_file = _fake_load_file


def render(view_name):
    """Render the tab under one note view; return the recorded expander labels."""
    st.reset()
    st.set_widget_value(VIEW_KEY, view_name)
    streamlit_app.tab_weekly_monitor(
        {"scope": SCOPE, "view": VIEW, "levels": [], "themes": [],
         "time_window": "All"}
    )
    return [c[2][0] for c in st.calls(method="expander") if c[2]]


# ---------------------------------------------------------------------------
# 1. Every view renders without raising.
# ---------------------------------------------------------------------------
rendered = {}
for view_name in streamlit_app._WEEK_VIEWS:
    try:
        rendered[view_name] = render(view_name)
        expect(f"{view_name!r} renders without error", True)
    except Exception as exc:  # noqa: BLE001 - the point is to catch anything
        expect(f"{view_name!r} renders without error", False, f"{type(exc).__name__}: {exc}")
        rendered[view_name] = []


def has_section(labels, header_fragment):
    return any(header_fragment in str(l) for l in labels)


# ---------------------------------------------------------------------------
# 2. PM view = section I only.
# ---------------------------------------------------------------------------
pm = rendered[streamlit_app._WEEK_VIEW_PM]
expect("PM view shows I", has_section(pm, "COMPRESSED WEEK NOTE"), f"labels={pm}")
for absent in ("MACRO SYNTHESIS", "SIGNAL SCOREBOARD", "CENTRAL BANK TAPE",
               "SIGNAL TENSION", "KEY RELEASES", "RED TEAM", "CONSENSUS SCAN"):
    expect(f"PM view hides {absent}", not has_section(pm, absent), f"labels={pm}")
expect("PM view shows no release cards",
       not has_section(pm, "South Africa"), f"labels={pm}")


# ---------------------------------------------------------------------------
# 3. Full analysis = A + B + D-H, never C, never I.
# ---------------------------------------------------------------------------
fa = rendered[streamlit_app._WEEK_VIEW_ANALYSIS]
for present in ("MACRO SYNTHESIS", "SIGNAL SCOREBOARD", "CENTRAL BANK TAPE",
                "SIGNAL TENSION", "KEY RELEASES", "RED TEAM", "CONSENSUS SCAN"):
    expect(f"Full analysis shows {present}", has_section(fa, present), f"labels={fa}")
expect("Full analysis hides I", not has_section(fa, "COMPRESSED WEEK NOTE"), f"labels={fa}")
expect("Full analysis shows no release cards",
       not has_section(fa, "South Africa - CPI"), f"labels={fa}")
expect("Full analysis does not render the C header as a section",
       not has_section(fa, "FULL RELEASE ARCHIVE"), f"labels={fa}")


# ---------------------------------------------------------------------------
# 4. Release archive = C as cards, plus the grouped tape card.
# ---------------------------------------------------------------------------
ar = rendered[streamlit_app._WEEK_VIEW_ARCHIVE]
expect("Archive view shows the release card",
       has_section(ar, "South Africa - CPI"), f"labels={ar}")
expect("Archive view shows the grouped Central Bank Tape card",
       has_section(ar, "Central Bank Tape"), f"labels={ar}")
expect("Archive view does not render narrative sections separately",
       not has_section(ar, "RED TEAM"), f"labels={ar}")


# ---------------------------------------------------------------------------
# 5. Full note = narrative sections AND release cards, tape not duplicated.
# ---------------------------------------------------------------------------
fn = rendered[streamlit_app._WEEK_VIEW_FULL]
expect("Full note shows I", has_section(fn, "COMPRESSED WEEK NOTE"), f"labels={fn}")
expect("Full note shows A", has_section(fn, "MACRO SYNTHESIS"), f"labels={fn}")
expect("Full note shows the release card",
       has_section(fn, "South Africa - CPI"), f"labels={fn}")
expect("Full note shows D once, as a section",
       has_section(fn, "CENTRAL BANK TAPE"), f"labels={fn}")
expect("Full note does not also add the grouped tape card",
       not has_section(fn, "Central Bank Tape"),
       f"tape rendered twice: {fn}")


# ---------------------------------------------------------------------------
# 6. An old-format note under the PM view explains itself instead of blanking.
# ---------------------------------------------------------------------------
OLD_FORMAT = NEW_FORMAT.split("H. CURRENCY")[0] + "<<ZAR_WEEK_END>>\n"
NEW_FORMAT_BACKUP = NEW_FORMAT
NEW_FORMAT = OLD_FORMAT
st.reset()
st.set_widget_value(VIEW_KEY, streamlit_app._WEEK_VIEW_PM)
streamlit_app.tab_weekly_monitor(
    {"scope": SCOPE, "view": VIEW, "levels": [], "themes": [], "time_window": "All"}
)
infos = [str(c[2][0]) for c in st.calls(method="info") if c[2]]
expect("old note under PM view explains the empty view, not silence",
       any("predates the A-I format" in i for i in infos),
       f"infos={infos}")
NEW_FORMAT = NEW_FORMAT_BACKUP


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
