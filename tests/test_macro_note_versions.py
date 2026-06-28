"""Regression test for the "Latest note only" bleed bug.

A real USD_MACRO_NOTE.txt stacks several note VERSIONS, newest first, each
wrapped in `<<USD_MACRO_NOTE_BEGIN>> ... <<USD_MACRO_NOTE_END>>`. The old
Macro Notes path used extract_blocks(split_weekly=True): its greedy marker
regex merged ALL versions into one block, then re-split that block at every
`Data window:` line. The "latest" fragment therefore ran from the newest
Data window line to the NEXT version's Data window line, dragging the
`<<END>>`/`<<BEGIN>>` markers and the previous note into the view.

extract_macro_note_versions must instead return one clean block per version.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.parsers import extract_macro_note_versions

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


# Two stacked versions, newest first -- mirrors the screenshot.
FILE = """\
<<USD_MACRO_NOTE_BEGIN>>
Data window: 18 May 2026 to 22 May 2026
The reaction function shifted decisively. Housing showed only conditional
stabilization.

Bottom Line
The U.S. is in policy-constrained stagflationary bifurcation.
<<USD_MACRO_NOTE_END>>
<<USD_MACRO_NOTE_BEGIN>>
USD Macro Note - PM Version
As of: 5 Apr 2026 (Paris)
Data window: 30 Mar 2026 to 3 Apr 2026
4-WEEK MACRO SIGNAL BOARD
Growth: down. Backward-looking Q1 demand held up.
<<<USD_MACRO_NOTE_END>>>
"""

versions = extract_macro_note_versions(FILE, source_file="USD_MACRO_NOTE.txt")

# 1. Exactly two versions, not one merged block and not N data-window frags.
expect("two versions parsed", len(versions) == 2, f"got {len(versions)}")

# 2. Newest-first window metadata is correct for each version.
if len(versions) == 2:
    wins = {v.data_window for v in versions}
    expect("latest version window present",
           "18 May 2026 to 22 May 2026" in wins, f"got {wins}")
    expect("previous version window present",
           "30 Mar 2026 to 3 Apr 2026" in wins, f"got {wins}")

    # Identify the latest-window block (this is what "Latest note only"
    # renders after _macro_note_versions sorts by end date desc).
    latest = next(v for v in versions
                  if v.data_window == "18 May 2026 to 22 May 2026")

    # 3. THE BUG: the latest block must NOT contain the next version's
    #    markers or body.
    expect("latest body has no BEGIN marker",
           "USD_MACRO_NOTE_BEGIN" not in latest.raw_text,
           "next version's BEGIN bled in")
    expect("latest body has no END marker",
           "USD_MACRO_NOTE_END" not in latest.raw_text,
           "END marker bled in")
    expect("latest body excludes PM Version preamble",
           "PM Version" not in latest.raw_text
           and "4-WEEK MACRO SIGNAL BOARD" not in latest.raw_text,
           "previous version's body bled into the latest note")
    expect("latest body excludes previous window line",
           "30 Mar 2026" not in latest.raw_text,
           "previous version's Data window bled in")

    # 4. The latest block keeps its own content.
    expect("latest body keeps its own content",
           "reaction function shifted" in latest.raw_text
           and "stagflationary bifurcation" in latest.raw_text)


# Single version with an inner <<END>> divider + triple terminator must stay
# one block with all content preserved.
SINGLE = """\
<<USD_MACRO_NOTE_BEGIN>>
Data window: 30 Mar 2026 to 3 Apr 2026
Brief summary before the divider.
<<USD_MACRO_NOTE_END>>
Executive Summary after the inner divider.
<<<USD_MACRO_NOTE_END>>>
trailing junk
"""
sv = extract_macro_note_versions(SINGLE, source_file="USD_MACRO_NOTE.txt")
expect("single divided note -> one block", len(sv) == 1, f"got {len(sv)}")
if sv:
    body = sv[0].raw_text
    expect("single note keeps pre-divider content",
           "Brief summary before the divider" in body)
    expect("single note keeps post-divider content",
           "Executive Summary after the inner divider" in body)
    expect("single note drops trailing junk",
           "trailing junk" not in body)
    expect("single note strips END markers",
           "USD_MACRO_NOTE_END" not in body)


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
