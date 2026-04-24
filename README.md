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

1. **Weekly Monitor** - pick a scope (region or currency) and a view
   (Frozen week / Live week / PM style / Macro note). An importance filter
   can reduce the view to *** and **** releases only.
2. **Macro Notes** - browse all `*_MACRO_NOTE.txt` files.
3. **Release Search** - keyword + scope + importance + theme + country filter
   across every release in every file. Cards or table view.
4. **Inflation Monitor** - preset search over CPI / HICP / PPI / WPI / PCE /
   wages / unit labor cost / import & export prices / inflation expectations.

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

## Smoke test

```bash
python smoke_test.py
```

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

