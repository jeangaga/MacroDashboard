# Macro FX Feed Dashboard

A structured macro terminal over the GitHub-hosted macro archive at
`jeangaga/mon-mini-chat-bot/notes/`. Four tabs, sidebar-driven filters,
optional `QUICK`-style command bar.

## What it does

- Parses the marker-delimited files in `notes/` (e.g. `<<AUD_WEEK_BEGIN>> ... <<AUD_WEEK_END>>`).
- Extracts individual release paragraphs and tags them with importance (*, **, ***, ****),
  detected countries, and theme (Inflation / Labor / Growth / Policy / FX / Housing).
- Lets you browse by scope + view, filter by importance/theme/country, or run a
  keyword search across the whole archive.
- Caches fetched files locally; if GitHub is unreachable you still get the stale copy.

## Tabs

1. **Week Recap** - the landing tile. Section `I` (compressed week note) for
   the most recent weeks, **stacked newest-first**, one below the other with a
   divider between them, so you read back through time by scrolling down. Two
   weeks by default; switch to 1, 3, 4, 6 or 8. Reads the scope's frozen WEEK
   file. Weeks with no `I` are counted in a caption rather than silently
   dropped. A **Raw text** checkbox switches from rendered markdown to the
   verbatim stored text.

   **Parts of the note to show** lists the note's own `###` subsections
   (Regime / Scoreboard / Major Release Tape / Minor Tape / Central Bank /
   Signal Tension / Key Releases / Red Team / FX Consensus). All are selected
   by default; narrowing to one reads that part across several weeks in a
   column — e.g. just the Scoreboard for the last four weeks. Options come
   from the notes actually on screen, so they follow the archive rather than a
   hardcoded list, and a week missing a selected part says so instead of
   rendering blank.
2. **Weekly Monitor** - pick a scope (region or currency) and a view
   (Frozen week / Live week / PM style / Macro note), then a **Note view** over
   the A-I spine (PM / Full analysis / Release archive / Full note). An
   importance filter can reduce the view to *** and **** releases only.
3. **Macro Synthesis** - cross-week view of section `A` prose and the section
   `B` signal scoreboard.
4. **Macro Notes** - browse all `*_MACRO_NOTE.txt` files.
5. **Country Release Catalogue** - per-country recurring releases, grouped by
   normalized name, with latest-vs-previous compare and a text export.

## Scopes

- **Regions (4):** USD, EUR, DM, EM
- **DM currencies (7):** AUD, CAD, CHF, GBP, JPY, NOK, SEK
- **EM currencies (9):** BRL, CNH, INR, KRW, MXN, PLN, TRY, TWD, ZAR
- **PM / shared (4):** WEEKPM, MACROPM, SHORT_WEEK, ARC

## Command bar shortcuts

Typed into the box at the top of the page:

| Command | Effect |
|---|---|
| `QUICK EUR` | regions=[EUR], min_importance=*** |
| `QUICK2AUD` | regions=[AUD], min_importance=**** |
| `CPI AUD` | query="CPI", regions=[AUD] |
| `**** inflation EM` | min_importance=****, themes=[Inflation], regions=[EM] |
| `labor US` | query="labor", regions=[USD] (via US alias) |

Unknown tokens flow into the free-text query.

## Install and run

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Then open the URL Streamlit prints (usually http://localhost:8501).

## Configuration

All defaults live in `core/config.py`. Environment variables can override:

| Var | Default | Use |
|---|---|---|
| `MACRO_REPO_OWNER` | `jeangaga` | GitHub owner |
| `MACRO_REPO_NAME` | `mon-mini-chat-bot` | Repo name |
| `MACRO_REPO_BRANCH` | `main` | Branch |
| `MACRO_REPO_NOTES_DIR` | `notes` | Subfolder containing `*.txt` |
| `GITHUB_TOKEN` | (unset) | Set for private repos; auth via Contents API |
| `MACRO_CACHE_TTL` | `300` (seconds) | How long a cached file is "fresh" |

## Cache

Fetched files are written to `data/cache/`. If GitHub is unreachable,
the app falls back to the cached copy and marks it `stale cache` in the
UI. Click **Refresh from GitHub** in the sidebar to bust the cache.

## WEEK note format (A-I)

A WEEK block is a lettered spine. **The letter is the parser identifier** —
the wording after it is not matched on, so a section can be retitled freely.

```
<<ZAR_WEEK_BEGIN>>
DATA WINDOW: [start] to [end]

A. ZAR WEEK - MACRO SYNTHESIS
B. ZAR MACRO SIGNAL SCOREBOARD
C. FULL RELEASE ARCHIVE            <- ends at D
D. CENTRAL BANK TAPE               <- always present
E. SIGNAL TENSION CHECK
F. 5 KEY RELEASES TO DIG INTO      <- five is a maximum, not a quota
G. RED TEAM QUESTIONS
H. CURRENCY MARKET-CONSENSUS SCAN  <- historical, as of the DATA WINDOW
I. COMPRESSED WEEK NOTE            <- PM digest, 30-60 seconds
<<ZAR_WEEK_END>>
```

- **A–H are the authoritative week object. I is a compressed derivative.**
  The dashboard renders I verbatim and never regenerates it from A–H, and
  never refreshes H against current market consensus — H is frozen as of that
  note's DATA WINDOW.
- `D` is always emitted. When there's no tape it carries the sentinel
  `No validated central-bank tape supplied for this window.` — the section
  still exists and the UI says so rather than hiding it.
- `H` and `I` contain `###` subsections (`### Bottom line`, `### Regime`, …).
  These are subsections of their parent letter, never top-level sections.
- `I` is embedded in the same `<<..._WEEK_BEGIN>>` block. There is no separate
  `<<..._WEEK_PM_BEGIN>>` marker.
- `DATA WINDOW` is authoritative; a WEEK note may span several calendar weeks.
- Same spine for every scope: USD, EUR, GBP, JPY, CAD, AUD, NZD, CHF, SEK,
  NOK, MXN, BRL, ZAR, CNH, …

### Backward compatibility

Older notes letter only A–C and leave `CENTRAL BANK TAPE`, `SIGNAL TENSION
CHECK`, `N KEY RELEASES TO DIG INTO` and `RED TEAM QUESTIONS` unlettered, with
no H or I at all. Those files keep working untouched: `extract_week_sections`
maps the unlettered headers onto the letters they would carry today (D/E/F/G),
so callers address sections by id without knowing which format produced the
file. Old files are never rewritten.

Numbered headings *inside* a release block (`1. Reuters Data`,
`3. Comment - Economist Layer`) are not top-level sections — digits can't match
`[A-I]`, and a header must additionally be ALL-CAPS to count as a spine entry.

**Heading level is ignored.** A section header may be written bare (`A. ...`)
or as a markdown heading (`# A. ...`, `## A. ...`); all forms parse the same
and the marker is stripped for display. A single real `USD_WEEK.txt` has
carried all three at once, so the number of leading hashes is not something the
parser depends on.

### Note views (Weekly Monitor)

| View | Renders |
|---|---|
| PM view | `I` only |
| Full analysis | `A`, `B`, `D`–`H` |
| Release archive | `C`, as release cards + the grouped tape card |
| Full note | `A`–`I` |

PM view is the default **when the displayed week actually has an `I`**;
otherwise the tab falls back to Release archive. Without that fallback every
pre-A-I note would open on a blank tab.

## Parser notes

- A file is split into blocks by `<<STEM_BEGIN>> ... <<STEM_END>>` markers.
  Files without markers are treated as a single implicit block.
- Within a block, release-sized paragraphs are those that contain at least
  one importance flag (`*`, `**`, `***`, or `****`). Paragraphs without flags
  are preserved in the full-block view on the Weekly Monitor tab but are
  not indexed for search.
- The raw block text is always preserved. Metadata (title, date, country,
  theme) is best-effort and never mutates the raw text.
- If you add a new currency file, edit `SCOPE_FILES`, `BLOCK_STEMS`, and
  (optionally) `SCOPE_COUNTRIES` in `core/config.py`.

## Tests

```bash
py run_tests.py
```

Runs all 18 suites in `tests/` offline and prints one summary
(currently **548 assertions, 0 failures**). Exits non-zero if anything
fails, and prints the tail of each failing suite's output.

| Flag | Effect |
|---|---|
| `-k catalogue` | only suites whose filename contains the string |
| `-v` | stream each suite's full output |
| `--real-streamlit` | import the installed streamlit instead of the stub |

Run this before uploading changed files to GitHub — the app is deployed
by hand-uploading, so a local pass is the only check that happens before
it goes live.

### Why there's a streamlit stub

Nine suites import `streamlit_app`, which needs `st.cache_data`,
`st.rerun` and row-selection `st.dataframe`. Any streamlit older than
~1.30 can't import it at all, so those suites were unrunnable on an old
local interpreter.

`tests/_stubs/streamlit.py` is an offline stand-in: it renders nothing,
records every display call, and returns each widget's declared default.
`run_tests.py` prepends `tests/_stubs` to `PYTHONPATH` for the test
subprocesses only.

**The stub can never affect the deployed app.** It sits in `tests/_stubs/`,
not the repo root, and nothing in the app adds that directory to
`sys.path` — Streamlit Cloud always imports the real package. Don't move
the file up a level.

The runner also repairs conda's unimportable `ssl` (Windows anaconda keeps
its OpenSSL DLLs in `Library\bin`, which is only on PATH inside an
activated conda shell) by prepending those directories for the subprocesses.

Tests can drive the stub:

```python
import streamlit as st
st.set_widget_value("cc_country", "Australia")   # simulate a selection
st.set_dataframe_selection("cc_table", [0])      # simulate a row click
st.rendered_text("caption")                      # what would have been drawn
st.reset()                                       # clear between cases
```

## Smoke test

```bash
py smoke_test.py
```

Older standalone test that pre-dates `tests/`, largely superseded by it.
Runs offline against a synthetic DM+EUR sample. Verifies parsing, release
extraction, country/theme tagging, importance filtering, and command
parsing. No network needed.

## Architecture

```
streamlit_app.py       Entry point - sidebar, tabs, command bar
core/
  config.py            GitHub coords, scope/file map, markers, themes
  loaders.py           GitHub fetch + local cache fallback
  parsers.py           Marker splitting + release extraction
  search.py            Filter + inflation preset + QUICK command parser
  render.py            Streamlit render helpers (cards, blocks, badges)
utils/
  github.py            Raw + Contents-API fetch
  text.py              Importance / date / country / theme detection
data/cache/            Local cache of fetched files
```

## Limitations and future work

- Date parsing is best-effort; sorting "by date" falls back to string
  compare when the parse fails.
- No semantic search yet - this is keyword + metadata only.
- No country dashboard or timeline charts (planned for v2).
- No PDF tab - saved PDFs aren't in the repo yet. Add `notes/pdf/` in
  GitHub and a minimal PDF library tab can be wired up quickly.

