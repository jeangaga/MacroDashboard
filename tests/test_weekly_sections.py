"""Regression test for the evolved weekly-note structure.

Covers two asks:
  1. A release's commentary must STOP at the next top-level section header
     (the "Reaction-function map ... CENTRAL BANK TAPE ... Summary" bleed).
  2. CENTRAL BANK TAPE content is tagged so the Weekly Monitor can group it
     into one card instead of peer release cards.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.parsers import (
    Block,
    extract_releases,
    extract_central_bank_tape_text,
    weekly_section_of,
)

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


# Faithful EUR_WEEK in the evolved format. The PMI release carries a
# "Reaction-function map" commentary paragraph; CENTRAL BANK TAPE follows
# immediately (this is the exact bleed the user reported).
NOTE = """\
A. EUR WEEK - MACRO SYNTHESIS

The week resolved into a policy-constrained configuration.

B. EUR MACRO SIGNAL SCOREBOARD

Growth: down

Eurozone - Euro Zone - S&P Manufacturing Final PMI (May)
Release Date: 1 Jun 2026 | Local Time: 09:00
Importance: ***
Reuters Data
S&P Manufacturing Final PMI: 49.4 | Prior: 49.0
Comment - Economist Layer
Survey-led downside call.

Reaction-function map: ECB: June tightening remains inflation-driven, but the GDP revision makes the optics worse. Next test: Q2 hard data and June PMIs.

CENTRAL BANK TAPE

Summary - Policy reaction function
The ECB tape confirms the week's Policy Constraint bucket rather than softening it.

Lagarde - 8 May 2026 carry-over
Release Date: 8 May 2026
Importance: ***
Reuters Data
Lagarde reiterated data-dependence.

Schnabel Reuters interview - 26 May 2026
Release Date: 26 May 2026
Importance: ****
Reuters Data
Schnabel pushed back on early cuts.

SIGNAL TENSION CHECK

The hard-data vs survey tension stays wide.

5 KEY RELEASES TO DIG INTO

1. Eurozone flash HICP.

RED TEAM QUESTIONS FOR JGM

What if Q2 hard data surprises up?
"""

b = Block(stem="EUR_WEEK", source_file="EUR_WEEK.txt", raw_text=NOTE)
rels = extract_releases(b)
titles = [r.title for r in rels]
print("    titles:", titles)

cb = [r for r in rels if r.section == "central_bank_tape"]
data = [r for r in rels if r.section != "central_bank_tape"]

# --- the data release is found and is NOT central_bank_tape ---
pmi = next((r for r in rels if "Manufacturing Final PMI" in (r.title or "")), None)
expect("PMI data release parsed", pmi is not None, f"titles={titles}")
if pmi:
    expect("PMI is a data release (not CB tape)",
           pmi.section != "central_bank_tape", f"section={pmi.section}")

    # --- THE BUG: commentary must stop at CENTRAL BANK TAPE ---
    expect("PMI keeps its own reaction-function commentary",
           "Reaction-function map" in pmi.raw_block
           and "Next test: Q2 hard data" in pmi.raw_block)
    expect("PMI does NOT absorb the CENTRAL BANK TAPE header",
           "CENTRAL BANK TAPE" not in pmi.raw_block,
           "section header bled into the release")
    expect("PMI does NOT absorb the tape summary",
           "The ECB tape confirms" not in pmi.raw_block
           and "Summary - Policy reaction function" not in pmi.raw_block,
           "tape summary bled into the release")

# --- CB speeches are tagged and grouped out of the data stream ---
expect("two central-bank-tape items tagged", len(cb) == 2, f"got {len(cb)} -> {[r.title for r in cb]}")
expect("Lagarde tagged central_bank_tape",
       any("Lagarde" in (r.title or "") for r in cb))
expect("Schnabel tagged central_bank_tape",
       any("Schnabel" in (r.title or "") for r in cb))
expect("CB speeches excluded from data releases",
       not any("Lagarde" in (r.title or "") or "Schnabel" in (r.title or "")
               for r in data))

# --- tape text extraction includes summary + speeches ---
tape = extract_central_bank_tape_text(b)
expect("tape text has the summary",
       "The ECB tape confirms" in tape)
expect("tape text has both speakers",
       "Lagarde" in tape and "Schnabel" in tape)
expect("tape text excludes the next section",
       "SIGNAL TENSION CHECK" not in tape and "RED TEAM" not in tape)


# --- Graceful: a weekly block with NO central bank tape ---
PLAIN = """\
United States - CPI (Mar)
Release Date: 15 Apr 2026
Importance: ****
Reuters Data
CPI: 2.6% | Prior: 2.4%
Comment - Economist Layer
Hotter than expected.
"""
b2 = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=PLAIN)
r2 = extract_releases(b2)
expect("plain block: one release", len(r2) == 1, f"got {len(r2)}")
expect("plain block: no CB tape tagged",
       not any(r.section == "central_bank_tape" for r in r2))
expect("plain block: empty tape text",
       extract_central_bank_tape_text(b2) == "")

print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
