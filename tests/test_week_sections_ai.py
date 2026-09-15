"""Regression tests for the A-I lettered WEEK note format.

The canonical WEEK object is now a lettered spine:

    A. MACRO SYNTHESIS      B. SIGNAL SCOREBOARD    C. FULL RELEASE ARCHIVE
    D. CENTRAL BANK TAPE    E. SIGNAL TENSION       F. 5 KEY RELEASES
    G. RED TEAM QUESTIONS   H. MARKET-CONSENSUS     I. COMPRESSED WEEK NOTE

Contract under test:
  - The LETTER is the parser identifier; the wording after it is not.
  - D is always present, possibly holding only the "no tape" sentinel.
  - F is capped at five, not quota'd to five.
  - H and I hold ### subsections that must stay inside their parent.
  - I is a compressed derivative: displayed verbatim, never regenerated.
  - Numbered sub-headings inside a release ("1. Reuters Data") are NOT sections.
  - Old notes without D-I must keep parsing exactly as before.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.parsers import (  # noqa: E402
    LETTER_SECTION_IDS,
    NARRATIVE_SECTION_IDS,
    extract_blocks,
    extract_central_bank_tape_text,
    extract_macro_synthesis,
    extract_releases,
    extract_week_sections,
    filter_subsections,
    has_week_section,
    split_subsections,
    subsection_titles,
    week_section_text,
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NEW_FORMAT = """\
<<ZAR_WEEK_BEGIN>>
DATA WINDOW: 3 Aug 2026 to 14 Aug 2026

A. ZAR WEEK - MACRO SYNTHESIS

The rand traded on a policy-constrained footing all window.

B. ZAR MACRO SIGNAL SCOREBOARD

Growth: -
Labor: ~
Inflation: +
Financial Conditions: ~
Policy Constraint: +

C. FULL RELEASE ARCHIVE

South Africa - CPI (Jul)
Release Date: 12 Aug 2026 | Local Time: 10:00
Importance: ****
1. Reuters Data
CPI YY: 4.6% | Prior: 4.4%
2. Professional Market Commentary
Desks read the print as sticky.
3. Comment - Economist Layer
Core momentum is the story.
4. HF Take - Strategist Layer
Front-end pricing looks complacent.

South Africa - Retail Sales (Jun)
Release Date: 13 Aug 2026 | Local Time: 13:00
Importance: ***
1. Reuters Data
Retail Sales YY: 1.2% | Prior: 2.0%

D. CENTRAL BANK TAPE

Summary - Policy reaction function
SARB stayed hawkish through the window.

Kganyago - 11 Aug 2026
Release Date: 11 Aug 2026
Importance: ***
1. Reuters Data
Kganyago pushed back on early cuts.

E. SIGNAL TENSION CHECK

Hard data and survey data disagree on momentum.

F. 5 KEY RELEASES TO DIG INTO

1. South Africa CPI (Jul).
2. South Africa Retail Sales (Jun).

G. RED TEAM QUESTIONS

What if the CPI print is revised down next month?

H. CURRENCY MARKET-CONSENSUS SCAN

### Bottom line
Consensus is mildly bearish ZAR into year-end.

### What changed through the data window
Positioning shifted toward carry.

### Main consensus drivers
Carry and terms of trade.

### Where consensus could be wrong
A hawkish SARB surprise would squeeze shorts.

I. COMPRESSED WEEK NOTE

### Regime
Policy-constrained, inflation-led.

### Scoreboard
Growth -, Inflation +.

### Major Release Tape
**** South Africa - CPI (Jul): 4.6% vs 4.4% prior

### Key Releases
CPI and Retail Sales.

### FX Consensus
Mildly bearish.

<<ZAR_WEEK_END>>
"""

# The old shape: only A-C lettered, narrative headers unlettered, no D-I.
OLD_FORMAT = """\
<<ZAR_WEEK_BEGIN>>
DATA WINDOW: 6 Jul 2026 to 10 Jul 2026

A. ZAR WEEK - MACRO SYNTHESIS

Older synthesis prose.

B. ZAR MACRO SIGNAL SCOREBOARD

Growth: -
Inflation: +

C. FULL RELEASE ARCHIVE

South Africa - CPI (Jun)
Release Date: 9 Jul 2026
Importance: ****
1. Reuters Data
CPI YY: 4.4% | Prior: 4.2%

CENTRAL BANK TAPE

Summary - Policy reaction function
SARB on hold.

SIGNAL TENSION CHECK

Tension is narrow.

3 KEY RELEASES TO DIG INTO

1. South Africa CPI (Jun).

RED TEAM QUESTIONS FOR JGM

What if growth rolls over?

<<ZAR_WEEK_END>>
"""

new_block = extract_blocks(NEW_FORMAT, source_file="ZAR_WEEK.txt")[0]
old_block = extract_blocks(OLD_FORMAT, source_file="ZAR_WEEK.txt")[0]


# ---------------------------------------------------------------------------
# 1. The letter is the identifier
# ---------------------------------------------------------------------------
for letter, sid in LETTER_SECTION_IDS.items():
    expect(f"weekly_section_of('{letter}. ...') -> {sid}",
           weekly_section_of(f"{letter}. SOMETHING ENTIRELY DIFFERENT") == sid,
           f"got {weekly_section_of(f'{letter}. SOMETHING ENTIRELY DIFFERENT')!r}")

# Wording after the letter is explicitly NOT load-bearing.
expect("F maps by letter even when retitled",
       weekly_section_of("F. 3 THINGS WORTH A SECOND LOOK") == "key_releases")
expect("D maps by letter even when retitled",
       weekly_section_of("D. POLICYMAKER TAPE") == "central_bank_tape")

# Numbered sub-headings inside a release must never be section headers.
for line in ("1. Reuters Data", "2. Professional Market Commentary",
             "3. Comment - Economist Layer", "4. HF Take - Strategist Layer"):
    expect(f"release sub-heading is not a section: {line!r}",
           weekly_section_of(line) is None,
           f"got {weekly_section_of(line)!r}")

# Prose that happens to start with a letter must not become a section.
expect("mixed-case prose 'A. The Fed said...' is not a section",
       weekly_section_of("A. The Fed said it would wait for more data") is None)
expect("stray 'Q4. revisions' is not a section",
       weekly_section_of("Q4. revisions were larger than expected") is None)


# ---------------------------------------------------------------------------
# 2. New format: all nine sections, in order, correctly bounded
# ---------------------------------------------------------------------------
secs = extract_week_sections(new_block)
letters = [s["letter"] for s in secs]
expect("new format yields 9 sections", len(secs) == 9, f"got {len(secs)}: {letters}")
expect("sections are in A-I document order",
       letters == list("ABCDEFGHI"), f"got {letters}")
expect("every new-format section is lettered",
       all(s["lettered"] for s in secs))

ids = [s["id"] for s in secs]
expect("ids follow LETTER_SECTION_IDS",
       ids == [LETTER_SECTION_IDS[l] for l in "ABCDEFGHI"], f"got {ids}")

# C is the release archive and must stop at D.
c_body = week_section_text(new_block, "archive")
expect("C contains its releases",
       "South Africa - CPI (Jul)" in c_body and "Retail Sales (Jun)" in c_body)
expect("C stops at D (no tape header)",
       "CENTRAL BANK TAPE" not in c_body, "section D bled into C")
expect("C stops at D (no tape body)",
       "SARB stayed hawkish" not in c_body, "tape body bled into C")
expect("C keeps the numbered release sub-headings",
       "1. Reuters Data" in c_body and "4. HF Take - Strategist Layer" in c_body,
       "release internals were treated as section boundaries")


# ---------------------------------------------------------------------------
# 3. D is always present; F is a maximum, not a quota
# ---------------------------------------------------------------------------
expect("D present in new format", has_week_section(new_block, "central_bank_tape"))

EMPTY_TAPE = NEW_FORMAT.replace(
    "Summary - Policy reaction function\nSARB stayed hawkish through the window.\n\n"
    "Kganyago - 11 Aug 2026\nRelease Date: 11 Aug 2026\nImportance: ***\n"
    "1. Reuters Data\nKganyago pushed back on early cuts.\n",
    "No validated central-bank tape supplied for this window.\n",
)
empty_block = extract_blocks(EMPTY_TAPE, source_file="ZAR_WEEK.txt")[0]
expect("D still present when it holds only the sentinel",
       has_week_section(empty_block, "central_bank_tape"),
       "a tape-less week lost its D section")
expect("D sentinel text is preserved",
       "No validated central-bank tape supplied" in
       week_section_text(empty_block, "central_bank_tape"))
expect("sentinel-only D does not leak into E",
       "No validated" not in week_section_text(empty_block, "signal_tension"))

f_body = week_section_text(new_block, "key_releases")
expect("F titled '5 KEY RELEASES' may hold fewer than five",
       "South Africa CPI (Jul)" in f_body and "Retail Sales (Jun)" in f_body)
expect("F stops at G",
       "RED TEAM" not in f_body and "What if the CPI print" not in f_body)


# ---------------------------------------------------------------------------
# 4. ### subsections stay inside their parent (H and I)
# ---------------------------------------------------------------------------
h_body = week_section_text(new_block, "fx_consensus")
for sub in ("### Bottom line", "### What changed through the data window",
            "### Main consensus drivers", "### Where consensus could be wrong"):
    expect(f"H keeps {sub!r}", sub in h_body, "H subsection escaped")
expect("H stops at I",
       "COMPRESSED WEEK NOTE" not in h_body and "Policy-constrained, inflation-led"
       not in h_body)

i_body = week_section_text(new_block, "compressed")
for sub in ("### Regime", "### Scoreboard", "### Major Release Tape",
            "### Key Releases", "### FX Consensus"):
    expect(f"I keeps {sub!r}", sub in i_body, "I subsection escaped")
expect("I is not split into further top-level sections",
       len([s for s in secs if s["id"] == "compressed"]) == 1)
expect("### headings are not top-level sections",
       weekly_section_of("### Regime") is None
       and weekly_section_of("### Bottom line") is None)

# --- splitting a section body into its ### subsections ---
expect("I splits into its five subsections",
       subsection_titles(i_body) == ["Regime", "Scoreboard", "Major Release Tape",
                                     "Key Releases", "FX Consensus"],
       f"got {subsection_titles(i_body)}")
expect("H splits into its four subsections",
       subsection_titles(h_body) == ["Bottom line",
                                     "What changed through the data window",
                                     "Main consensus drivers",
                                     "Where consensus could be wrong"],
       f"got {subsection_titles(h_body)}")

subs = dict(split_subsections(i_body))
expect("subsection bodies are captured",
       "Policy-constrained, inflation-led." in subs["Regime"], f"got {subs.get('Regime')!r}")
expect("a subsection body stops at the next heading",
       "Scoreboard" not in subs["Regime"])

# `####` is content inside a subsection, not a new one -- splitting on it would
# flatten the note's own hierarchy.
nested = "### Regime\n\nTop line.\n\n#### Detail\n\nNested body.\n\n### Scoreboard\n\nGlyphs.\n"
expect("#### does not start a new subsection",
       subsection_titles(nested) == ["Regime", "Scoreboard"],
       f"got {subsection_titles(nested)}")
expect("#### stays inside its parent",
       "#### Detail" in dict(split_subsections(nested))["Regime"])

# Text before the first heading is preserved rather than dropped.
pre = "Lead-in prose.\n\n### Regime\n\nBody.\n"
expect("preamble before the first heading is kept",
       split_subsections(pre)[0] == ("", "Lead-in prose."),
       f"got {split_subsections(pre)[0]!r}")
expect("split_subsections is safe on empty input",
       split_subsections("") == [] and split_subsections(None) == [])

# --- filtering to selected subsections ---
only_regime = filter_subsections(i_body, ["Regime"])
expect("filter keeps the selected subsection with its heading",
       only_regime.startswith("### Regime") and "Policy-constrained, inflation-led." in only_regime,
       f"got {only_regime!r}")
expect("filter drops the unselected subsections",
       "Scoreboard" not in only_regime and "FX Consensus" not in only_regime)
expect("filter keeps document order, not selection order",
       subsection_titles(filter_subsections(i_body, ["FX Consensus", "Regime"]))
       == ["Regime", "FX Consensus"],
       f"got {subsection_titles(filter_subsections(i_body, ['FX Consensus', 'Regime']))}")
expect("filter with None keeps everything", filter_subsections(i_body, None) == i_body)
expect("filter with an empty selection keeps nothing",
       filter_subsections(i_body, []) == "")
expect("filter always keeps the preamble",
       filter_subsections(pre, []) == "Lead-in prose.",
       f"got {filter_subsections(pre, [])!r}")
expect("filter ignores titles the note doesn't have",
       filter_subsections(i_body, ["Regime", "Nonexistent"]) == only_regime)


# ---------------------------------------------------------------------------
# 5. Releases are tagged by the section they came from; I never pollutes C
# ---------------------------------------------------------------------------
rels = extract_releases(new_block)
by_section = {}
for r in rels:
    by_section.setdefault(getattr(r, "section", "data"), []).append(r)

archive = by_section.get("archive", [])
expect("C releases tagged 'archive'", len(archive) == 2,
       f"got {len(archive)}: {[r.title for r in archive]}")
expect("CPI parsed out of C",
       any("CPI" in (r.title or "") for r in archive))

tape = by_section.get("central_bank_tape", [])
expect("D speaker item tagged central_bank_tape", len(tape) == 1,
       f"got {[r.title for r in tape]}")
expect("Kganyago is the tape item",
       any("Kganyago" in (r.title or "") for r in tape))

# The compressed note quotes a release ("**** South Africa - CPI (Jul): 4.6%").
# It must never surface as a peer release card in the archive.
data_stream = [r for r in rels
               if getattr(r, "section", "data") != "central_bank_tape"
               and getattr(r, "section", "data") not in NARRATIVE_SECTION_IDS]
expect("compressed-note quote does not become a phantom release",
       len(data_stream) == 2,
       f"got {len(data_stream)}: {[(r.title, r.section) for r in data_stream]}")
expect("NARRATIVE_SECTION_IDS covers I and H",
       "compressed" in NARRATIVE_SECTION_IDS and "fx_consensus" in NARRATIVE_SECTION_IDS)
expect("NARRATIVE_SECTION_IDS does not swallow the archive",
       "archive" not in NARRATIVE_SECTION_IDS
       and "synthesis" not in NARRATIVE_SECTION_IDS)


# ---------------------------------------------------------------------------
# 6. Existing extractors keep working on the lettered format
# ---------------------------------------------------------------------------
tape_text = extract_central_bank_tape_text(new_block)
expect("tape text found via lettered D", "SARB stayed hawkish" in tape_text)
expect("tape text stops at E",
       "SIGNAL TENSION CHECK" not in tape_text
       and "Hard data and survey data" not in tape_text)

synth = extract_macro_synthesis(new_block)
expect("A prose extracted", "policy-constrained footing" in synth["synthesis"])
expect("B signals extracted", len(synth["signals"]) == 5,
       f"got {[s[0] for s in synth['signals']]}")
expect("F located despite being lettered now",
       "South Africa CPI (Jul)" in synth["key_releases"],
       f"got {synth['key_releases']!r}")


# ---------------------------------------------------------------------------
# 7. Backward compatibility: old notes keep parsing, mapped onto the same ids
# ---------------------------------------------------------------------------
old_secs = extract_week_sections(old_block)
old_ids = [s["id"] for s in old_secs]
expect("old format still yields its 7 sections", len(old_secs) == 7,
       f"got {len(old_secs)}: {old_ids}")
expect("old unlettered headers map onto canonical ids",
       old_ids == ["synthesis", "scoreboard", "archive", "central_bank_tape",
                   "signal_tension", "key_releases", "red_team"],
       f"got {old_ids}")

lettered = {s["id"]: s["lettered"] for s in old_secs}
expect("old A-C are really lettered",
       lettered["synthesis"] and lettered["scoreboard"] and lettered["archive"])
expect("old D-G are inferred, not lettered",
       not lettered["central_bank_tape"] and not lettered["signal_tension"]
       and not lettered["key_releases"] and not lettered["red_team"])
expect("inferred sections still carry their canonical letter",
       [s["letter"] for s in old_secs] == list("ABCDEFG"),
       f"got {[s['letter'] for s in old_secs]}")

expect("old format has no compressed section",
       not has_week_section(old_block, "compressed"))
expect("old format has no consensus section",
       not has_week_section(old_block, "fx_consensus"))
expect("old tape still extracted", "SARB on hold" in
       extract_central_bank_tape_text(old_block))
expect("old '3 KEY RELEASES' still found",
       "South Africa CPI (Jun)" in week_section_text(old_block, "key_releases"))


# ---------------------------------------------------------------------------
# 8. Display wiring: default view, and what each view renders
# ---------------------------------------------------------------------------
import streamlit_app  # noqa: E402

expect("new-format note defaults to the PM view",
       streamlit_app._default_week_view([new_block]) == streamlit_app._WEEK_VIEW_PM,
       f"got {streamlit_app._default_week_view([new_block])!r}")
expect("old-format note falls back to the release archive",
       streamlit_app._default_week_view([old_block]) == streamlit_app._WEEK_VIEW_ARCHIVE,
       f"got {streamlit_app._default_week_view([old_block])!r}")
expect("mixed set defaults to PM when any week has an I",
       streamlit_app._default_week_view([old_block, new_block])
       == streamlit_app._WEEK_VIEW_PM)
expect("empty set falls back to the archive",
       streamlit_app._default_week_view([]) == streamlit_app._WEEK_VIEW_ARCHIVE)

views = streamlit_app._WEEK_VIEW_SECTIONS
expect("PM view renders section I only",
       views[streamlit_app._WEEK_VIEW_PM] == ["compressed"])
expect("Full analysis is A, B, D-H (never C, never I)",
       views[streamlit_app._WEEK_VIEW_ANALYSIS] ==
       ["synthesis", "scoreboard", "central_bank_tape", "signal_tension",
        "key_releases", "red_team", "fx_consensus"],
       f"got {views[streamlit_app._WEEK_VIEW_ANALYSIS]}")
expect("Full analysis excludes the archive",
       "archive" not in views[streamlit_app._WEEK_VIEW_ANALYSIS])
expect("Full note covers A-I",
       set(views[streamlit_app._WEEK_VIEW_FULL]) ==
       set(LETTER_SECTION_IDS.values()) - {"archive"},
       f"got {views[streamlit_app._WEEK_VIEW_FULL]}")
expect("archive + full note are the release-card views",
       streamlit_app._WEEK_VIEWS_WITH_RELEASES ==
       {streamlit_app._WEEK_VIEW_ARCHIVE, streamlit_app._WEEK_VIEW_FULL})

# The view seeder must not stomp a manual choice.
sess = {}
key = "wm_note_view_ZAR_frozen_week"
streamlit_app._seed_week_view(sess, key, streamlit_app._WEEK_VIEW_PM)
expect("seeder writes the default on first render",
       sess[key] == streamlit_app._WEEK_VIEW_PM)
sess[key] = streamlit_app._WEEK_VIEW_ARCHIVE          # user picks something else
streamlit_app._seed_week_view(sess, key, streamlit_app._WEEK_VIEW_PM)
expect("seeder leaves a manual choice alone on rerun",
       sess[key] == streamlit_app._WEEK_VIEW_ARCHIVE,
       f"got {sess[key]!r}")
streamlit_app._seed_week_view(sess, key, streamlit_app._WEEK_VIEW_ARCHIVE)
expect("seeder re-seeds when the computed default changes",
       sess[key] == streamlit_app._WEEK_VIEW_ARCHIVE)


# ---------------------------------------------------------------------------
# 9. Markdown-prefixed headers: the heading level is NOT part of the contract
# ---------------------------------------------------------------------------
# A real USD_WEEK.txt carried the same spine three ways at once -- bare `A.`,
# `# A.` and `## A.` -- because the note author changed heading style partway
# through the archive. Both affected weeks parsed as ZERO sections (no A, no I,
# and their releases mis-parsed too) until the prefix was allowed.
for prefix in ("", "# ", "## ", "### ", "#### "):
    got = weekly_section_of(prefix + "I. COMPRESSED WEEK NOTE")
    expect(f"{prefix + 'I.'!r} still maps by letter", got == "compressed",
           f"got {got!r}")

HASHED = NEW_FORMAT.replace("\nA. ", "\n# A. ").replace("\nB. ", "\n## B. ")
hb = extract_blocks(HASHED, source_file="ZAR_WEEK.txt")[0]
hsecs = extract_week_sections(hb)
expect("mixed heading levels in one note still yield all nine sections",
       [s["letter"] for s in hsecs] == list("ABCDEFGHI"),
       f"got {[s['letter'] for s in hsecs]}")
expect("header text drops the markdown marker",
       [s["header"] for s in hsecs][:2]
       == ["A. ZAR WEEK - MACRO SYNTHESIS", "B. ZAR MACRO SIGNAL SCOREBOARD"],
       f"got {[s['header'] for s in hsecs][:2]}")
expect("hashed A still yields its prose",
       "policy-constrained footing" in week_section_text(hb, "synthesis"))
expect("hashed note still finds the compressed section",
       "### Regime" in week_section_text(hb, "compressed"))
expect("hashed note still bounds C at D",
       "CENTRAL BANK TAPE" not in week_section_text(hb, "archive"))

# Release sub-headings are markdown in the new files too; digits keep them out
# of the spine no matter how many hashes precede them.
for line in ("### 1. Reuters Data", "### 3. Comment - Economist Layer",
             "## 2. Professional Market Commentary",
             "# 4. HF Take - Strategist Layer"):
    expect(f"markdown release sub-heading is still not a section: {line!r}",
           weekly_section_of(line) is None, f"got {weekly_section_of(line)!r}")
expect("### Regime is still a subsection, not a section",
       weekly_section_of("### Regime") is None)
expect("a hashed lowercase line is still not a section",
       weekly_section_of("# A. The Fed said it would wait") is None)


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
