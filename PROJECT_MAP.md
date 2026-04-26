# MacroDashboard — Project Map

A Streamlit dashboard over the GitHub-hosted macro-research archive
`jeangaga/mon-mini-chat-bot/notes/*.txt`. Files use marker delimiters
(`<<USD_WEEK_BEGIN>>...<<USD_WEEK_END>>`) and may contain multiple
`Data window:` sections per block.

Total: ~4,000 lines of Python across 19 modules + 8 test suites.

## High-level architecture

```
streamlit_app.py         (UI entry point - 1025 lines)
        |
        +--> core/config.py        scopes, files, themes, country priority map
        +--> core/loaders.py       cache + GitHub fetch
        |       \-- utils/github.py
        +--> core/parsers.py       marker -> Block -> Release
        |       \-- utils/text.py
        +--> core/normalize.py     release-name canonicalization + dedup
        +--> core/search.py        filter/sort/command-parse
        +--> core/render.py        Streamlit widget helpers
```

Data flow at runtime: sidebar picks scope -> tabs call `_load_many()` -> cached
GitHub fetch -> `extract_blocks()` -> `extract_releases()` -> filter / dedup /
group -> Streamlit render.

## Dependency graph (what imports what)

| Module | Imports from project | External | Side effects |
|---|---|---|---|
| `streamlit_app.py` | `core.*`, `utils.text` | streamlit, pandas | Streamlit, cache I/O, network |
| `core/config.py` | — | os, pathlib | Reads env vars; mkdir cache |
| `core/loaders.py` | `core.config`, `utils.github` | — | filesystem (cache), network |
| `core/parsers.py` | `core.config`, `utils.text` | re, dataclasses | none (pure) |
| `core/normalize.py` | `utils.text` | re, dataclasses | none (pure) |
| `core/render.py` | `core.{config, loaders, parsers}`, `utils.text` | streamlit | Streamlit |
| `core/search.py` | `core.{config, parsers}`, `utils.text` | pandas | none (pure) |
| `utils/github.py` | `core.config` | requests, base64 | network |
| `utils/text.py` | `core.config` | re, datetime, calendar | none (pure) |
| `tests/*` | `core.*`, `utils.*`, sometimes `streamlit_app` | — | none |

The pure modules (`core.parsers`, `core.normalize`, `core.search`,
`utils.text`) are the audit hot zone — every assertion in `tests/` exercises
them. `streamlit_app.py` is the only file with widget-state coupling.

---

## streamlit_app.py — UI entry point

Tabs: Weekly Monitor, Macro Notes, Release Search, Theme Monitor, Country
Release Catalogue. Sidebar drives scope/view/importance/themes/time-window.

### Constants

- `IMPORTANCE_LEVELS_UI` — `["*", "**", "***", "****"]` for filter widgets.
- `TIME_WINDOWS` — six labels (`All`, `Last 4 weeks`, …) used by Release
  Search and Theme Monitor.
- `_MACRO_NOTE_VIEWS` — `["Latest note only", "Previous notes", "All notes archive"]`.
- `_CMD_HELP` — Markdown table shown when user clicks `?` in the command bar.
- `_CONFIDENCE_ICON` — `{High:H, Medium:M, Low:L}` for catalogue table.
- `_CATALOGUE_THEMES` — six themes used in catalogue filter.
- `_SCOPE_RESET_KEYS` — tuple of widget keys cleared on scope change.

### Cache plumbing

- `_cached_load_file(filename, version)` — `@st.cache_data(ttl=300)` wrapper around `loaders.load_file`.
- `_cached_load_many(filenames, version)` — `@st.cache_data(ttl=300)` wrapper around `loaders.load_many`.
- `_refresh_token()` — reads `st.session_state["refresh_token"]`; bumped by sidebar Refresh button to invalidate cache.
- `_load_file(filename)` / `_load_many(filenames)` — thin wrappers passing the refresh token in.

### Sidebar / scope helpers

- `_scope_label(scope)` — formats `"USD  -  Region"` for selectbox.
- `_available_views(scope)` — returns `[(view_key, filename), …]` in priority order.
- `_view_display(view_key)` — `frozen_week → "Frozen week"` etc.
- `sidebar()` — renders the whole sidebar, returns `{scope, view, levels, themes, time_window}`. Source of truth for scope.

### Scope as a global state driver (added Apr 2026)

- `_reset_state_for_scope(new_scope, session=None)` — pure function; pops every key in `_SCOPE_RESET_KEYS`, clears `active_command`, pre-seeds `cc_country` to `default_catalogue_country(new_scope)`, advances `_prev_scope`. Injectable `session` for unit tests.
- `_handle_scope_change(scope)` — called immediately after `sidebar()`. First render: just records scope. On real change: calls `_reset_state_for_scope` then `st.rerun()` so widgets pick up new defaults.

### Command bar

- `_CMD_HELP` constant (above).
- `command_bar()` — text input + Run/Help/Clear buttons + deep-search checkbox. Returns parsed command dict (`{regions, themes, query, min_importance, _deep_search}`) or persisted `active_command`.
- `_command_summary(cmd, sidebar_state)` — single-line filter recap, e.g. `scopes=USD  |  importance>=***  |  query='CPI'`.
- `render_command_results(command_state, sidebar_state)` — when a command is active, runs the filter across `ALL_NOTE_FILES` and renders cards.

### Tab functions

- `tab_weekly_monitor(state)` — loads `SCOPE_FILES[scope][view]`, splits blocks by data window, deduplicates, week selector defaults to **All weeks** (`index=0`), sort order user-toggleable.
- `_macro_note_versions(blocks)` — sorts note blocks by end-date desc, start-date desc, stable index. Window-less blocks sink to bottom. Returns 5-tuples `(block, label, start, end, idx)`.
- `tab_macro_notes(state)` — file selector defaults to scope's macro-note file. View dropdown picks Latest only / Previous / All archive. Header (`File: … | Scope: … | Latest data window: …`) rendered exactly once.
- `tab_release_search(sidebar_state, command_state)` — query / scopes / themes / levels / time-window / release-type / countries / deep-search. Results shown as Cards or Table.
- `tab_theme_monitor(sidebar_state)` — focused recap per theme (Inflation/Labor/…) with time-window + scope + countries filter.
- `_release_sort_key(r)` — date-or-min sort key used by catalogue.
- `tab_country_release_catalogue()` — country selector built from `COUNTRY_SOURCE_PRIORITY.keys()`. Loads only the country's allow-listed source files (frozen by default; live optional). Groups releases by `normalize_release_name` and renders a sortable dataframe; row click opens latest + previous + earlier occurrences with optional latest-vs-previous compare.

### Entry point

- `main()` — order: `sidebar()` -> `_handle_scope_change(state['scope'])` -> title -> `Current scope: {scope}` caption -> `command_bar()` -> 5 tabs.
- `if __name__ == "__main__": main()`.

---

## core/

### core/config.py — configuration constants

Pure-data module. Defines every constant the rest of the app keys off.

**GitHub source** — `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_BRANCH`,
`GITHUB_NOTES_DIR`, `GITHUB_TOKEN` (env-driven, defaults to
`jeangaga/mon-mini-chat-bot/main/notes`).

**Cache** — `PROJECT_ROOT`, `CACHE_DIR` (auto-created), `CACHE_TTL_SECONDS`.

**Scope taxonomy** — `REGION_SCOPES` (USD/EUR/DM/EM), `CURRENCY_SCOPES_DM`
(7), `CURRENCY_SCOPES_EM` (9), `PM_SCOPES` (4), `ALL_SCOPES`, `SCOPE_GROUP`,
`REGIONS` (alias).

**Scope→files** — `SCOPE_FILES` maps each scope to `{frozen_week, live_week,
pm_style, macro_note}` filenames. `REGION_FILES` is an alias. `ALL_NOTE_FILES`
is the deduped union.

**Markers** — `MARKER_PREFIX = "<<"`, `MARKER_SUFFIX = ">>"`, `BLOCK_STEMS`
(known stems per kind).

**Importance** — `IMPORTANCE_LEVELS`, `IMPORTANCE_LABELS`.

**Themes** — `THEME_KEYWORDS` maps theme name → list of detection keywords,
`ALL_THEMES`.

**Countries** — `COUNTRY_ALIASES` (canonical name → aliases),
`SCOPE_COUNTRIES` (scope → countries), `REGION_COUNTRIES` (alias).

**Country source priority** — `COUNTRY_SOURCE_PRIORITY` maps each country to
`{frozen: [...], live: [...]}`. This is the allow-list that prevents a US
catalogue query from pulling EUR_WEEK rows.

**Helpers**

- `sources_for_country(country, *, include_live=False)` — ordered file list, country-specific first then regional fallback. Live appended only when toggle on.
- `country_source_status(filename)` — classifies as `frozen` / `live` / `other` for UI badging.
- `_SCOPE_DEFAULT_COUNTRY_OVERRIDES` — `{EUR: "Eurozone", DM: "UK", EM: "China"}`.
- `default_catalogue_country(scope)` — representative country for catalogue tab when scope changes. Region scopes use overrides; currency scopes pick the single mapped country; PM scopes return None.

### core/loaders.py — fetch with cache fallback

`LoadResult` dataclass: `filename, text, source ∈ {cache, github, cache-stale}, fetched_at, error`.

- `_cache_path(filename)` — path under `data/cache/`, with `/` -> `__`.
- `_read_cache(filename)` / `_write_cache(filename, text)` — silent on OSError.
- `load_file(filename, *, force_refresh=False)` — fresh-cache hit if age < TTL; else GitHub via `utils.github.fetch_file`; on failure, returns stale cache if any, else error-only LoadResult.
- `load_many(filenames, *, force_refresh=False)` — list comprehension over `load_file`, skipping empty filenames.
- `load_all_notes(*, force_refresh=False)` — convenience over `ALL_NOTE_FILES`.

### core/parsers.py — marker-based parsing

Two-layer parser: file → blocks → releases. **Critical regression-tested code.**

**Dataclasses**

- `Block` — `stem, source_file, raw_text, data_window, data_window_start, data_window_end`. Properties `region` (derived from stem) and `kind` (`frozen_week / live_week / pm_style / macro_note`).
- `Release` — `source_file, block_stem, region, kind, title, importance, date_str, countries, themes, raw_block`. Property `importance_rank = len(importance)`.

**Sets / regexes / commentary filters**

- `_KNOWN_SCOPES`, `_SHARED_STEMS` — recognized prefixes.
- `_PARAGRAPH_SPLIT`, `_DAY_HEADER_RE`, `_DATA_WINDOW_RE`, `_RELEASE_FIELD_RE`, `_TITLE_DASH_RE` — regexes.
- `_TITLE_SKIP_PREFIXES` — tokens that disqualify a line as a title.
- `_COMMENTARY_PREFIXES`, `_NARRATIVE_PHRASES` — strings used by the commentary-fragment guard.

**Stem helpers**

- `_all_known_stems()` — flattens `BLOCK_STEMS`.
- `_stem_to_region(stem)` — `USD_WEEK_LIVE_MACRO -> USD`, `WEEKPM -> ""`.
- `_stem_to_kind(stem)` — suffix-based.
- `_marker_regex(stem)` — `<<STEM_BEGIN>>(.*?)<<STEM_END>>` with DOTALL.
- `_stem_from_filename(filename)` — uppercase basename minus extension.

**Block extraction**

- `extract_blocks(text, source_file, *, split_weekly=True)` — finds every marker pair, optionally splits each block by inline `Data window:` headers. Falls back to a single-block extraction when the file has no markers.
- `find_data_windows(text)` — list of `(label, start_date, end_date, match_start, match_end)`.
- `split_block_by_data_window(block)` — splits a Block into per-window sub-Blocks; returns `[block]` if none found.
- `block_data_window(block)` — `(label, start_date, end_date)`. Prefers explicit header; otherwise infers from min/max release dates.

**Release extraction (the gnarly part)**

- `_is_day_header_line(line)` / `_is_day_header_paragraph(p)` / `_strip_day_header_lines(p)` — strip `MONDAY 13 APR 2026` markers.
- `_has_release_signals(text)` — true when text contains structured fields (`Importance:`, `Release Date:`) or a country-dashed title.
- `_looks_like_title_line(line)` — title heuristic. Wires the commentary guard in.
- `_looks_like_commentary_fragment(line)` — rejects narrative prose: matches `_COMMENTARY_PREFIXES`, then narrative phrases, then long-dashless prose with > 16 words.
- `_looks_like_preamble(p)` — first-paragraph title detection.
- `_best_title_line(p)`, `_first_meaningful_line(text)`, `_clean_title(title)` — title normalization.
- `extract_releases(block)` — main entry. Splits raw_text on importance flags, runs the title guard, extracts `(title, importance, date_str, countries, themes)`, returns list of `Release`.

**Integration helpers**

- `blocks_from_load_results(results)` / `releases_from_load_results(results)` — convenience over a list of `LoadResult`.

### core/normalize.py — release-name canonicalization

Maps free-form release titles to canonical recurring-release names with theme
and confidence. **Pure, regression-tested.**

- `_RULES` — ordered list of `(compiled_regex, canonical_name, theme, confidence)` tuples. Specific rules first (e.g. `"non-farm payrolls"`), generic fallback last. Covers Inflation, Labor, Policy, Growth, External, Housing.
- `normalize_release_name(title)` — returns `(canonical_name, theme, confidence ∈ {High, Medium, Low})`.
- `is_known(title)` — confidence in {High, Medium}.
- `release_key(release)` — stable dedup key `f"{country}|{normalized_name}|{date}|{importance}"`. Used to detect duplicate parses of the same Reuters event across files.
- `dedup_releases(releases)` — keeps first occurrence by `release_key`. **Frozen sources come first in `sources_for_country`, so frozen wins over live duplicates.**

### core/render.py — Streamlit widget helpers

All functions touch `st.*`.

- `source_badge(result)` — formats `LoadResult` source + timestamp.
- `importance_chip(flag)` — formats importance flag with label.
- `render_block(block, *, min_importance=None, levels=None)` — block header + filtered release cards or raw code dump.
- `render_release_card(release, *, default_expanded=False)` — collapsed-by-default expander showing title, metadata, raw block.
- `render_release_list(releases, *, empty_message="...", limit=None)` — count caption + list of cards, optionally capped.
- `render_load_status(results)` — caption with loaded/stale/missing counts.

### core/search.py — filter/sort/command-parse

Pure module, no Streamlit.

**DataFrame**

- `releases_to_dataframe(releases)` — pandas DataFrame, sorted by `(importance_rank desc, date desc, title asc)`.

**Filter**

- `_haystack_metadata(r)` — default search blob: `title + countries + themes + region + release_type` (excludes raw_block unless deep search is on).
- `filter_releases(releases, *, query, regions, min_importance, levels, themes, countries, kinds, source_files, release_types, since, until, deep_search)` — single-pass filter with `levels` overriding `min_importance`. Drops releases whose date can't be parsed if a `since/until` is given.

**Theme / type**

- `inflation_releases(releases)` — alias for `theme_releases(releases, "Inflation")`.
- `theme_releases(releases, theme)` — filters by `THEME_KEYWORDS[theme]`, sorts by importance/date/title.
- `release_types_for(releases, scopes=None, countries=None)` — distinct canonical release names for the dropdown.

**Time window**

- `time_window_to_since(label, today=None)` — UI label → `datetime.date` or None (`All`).

**Command bar**

- `_SCOPE_ALIASES` — `US -> USD`, `UK -> GBP`, etc.
- `_resolve_scope(token, valid_scopes)` — alias resolver.
- `parse_command(cmd)` — handles `QUICK2USD`, `QUICK EUR`, and free-form `"**** inflation EM"`. Returns `{regions, min_importance, themes, query}`.

---

## utils/

### utils/github.py — GitHub fetch

- `GitHubFetchError` — raised on network/auth/404.
- `raw_url(filename)` — `raw.githubusercontent.com/<owner>/<repo>/<branch>/notes/<filename>`.
- `contents_api_url(filename)` — `api.github.com/repos/<owner>/<repo>/contents/notes/<filename>?ref=<branch>`.
- `fetch_file(filename, timeout=10.0)` — Contents API if `GITHUB_TOKEN` set (token + 5000 req/h limit), else raw.
- `_fetch_via_raw(filename, timeout)` / `_fetch_via_contents_api(filename, timeout)` — internals; the latter base64-decodes the response.
- `probe_file(filename, timeout=5.0)` — HEAD request, returns Content-Length or None.

### utils/text.py — text helpers

Importance, country, theme, date, release-type extraction. Pure module.

**Importance**

- `_IMPORTANCE_RE` — standalone `*` to `****` regex.
- `max_importance(text)` — longest run of `*` found, or None.
- `importance_rank(flag)` — `len(flag)`, 0–4.

**Countries**

- `_build_country_patterns()` — compiles per-country regex with **word boundaries** (`(?<!\w)alias(?!\w)`). This was added to fix a bug where `US` matched `BUSINESS`.
- `_COUNTRY_PATTERNS` — module-level cache.
- `detect_countries(text)` — list of countries matched anywhere.
- `country_from_title(title)` — at most one country, scanning only the first line.

**Themes**

- `detect_themes(text)` — list of themes whose keywords appear in `text`.

**Dates**

- `_DATE_PATTERNS` — four regexes for `13 Apr 2026`, `Apr 13, 2026`, `2026-04-13`, `13/04/2026`.
- `_MONTH_ABBR` — month abbr lookup.
- `first_date_string(text)` — first match, no parsing.
- `parse_release_date(text)` — `datetime.date` or None. Heuristic for US vs DD/MM order.

**Titles**

- `_PERIOD_PARENS`, `_TRAILING_DATE`, `_SEPARATORS` — regex/string patterns.
- `release_type(title)` — strips country prefix, period parens, trailing date. `"United States - PPI Final Demand (Mar)"` -> `"PPI Final Demand"`.

**Misc**

- `collapse_blank_lines(text)` — `\n\n\n+ -> \n\n`.
- `any_keyword(text, keywords)` — case-insensitive match.

---

## tests/ — regression suites

Each test runs as `python3 tests/test_*.py` and prints `N ok, M fail`. CI wrapper isn't formal; user runs all 8 manually. Total ~290 assertions across 1,150 lines.

- **test_catalogue.py** (115 lines) — synthetic Australia file; verifies `normalize_release_name` groups CPI/Labour Force correctly and the catalogue picks the latest occurrence per group.
- **test_catalogue_sources.py** (227 lines, 109 checks) — `sources_for_country` priority order; `country_source_status` classification; commentary-fragment rejection (`_looks_like_commentary_fragment`); end-to-end synthetic block parsing; frozen-wins-over-live dedup.
- **test_country.py** (83 lines, 19 checks) — country-aliasing word boundaries (US doesn't match BUSINESS, BONUS); `detect_countries`; NFP rule specificity (UK HMRC Payrolls ≠ NFP, real "Non-Farm Payrolls" still matches).
- **test_dedup.py** (96 lines, 10 checks) — `release_key` matches across files for the same event, differs across dates; `dedup_releases` empty/None safety; catalogue grouping post-dedup; day-header-only blocks emit zero releases.
- **test_macro_notes.py** (203 lines, 27 checks) — `_macro_note_versions` 5-tuple shape and end-date-desc sort; window-less blocks sink to bottom; end-to-end marker-file parsing; Weekly Monitor `index=0` "All weeks" default; Macro Notes scope-aware default; header rendered exactly once in `tab_macro_notes`.
- **test_normalize.py** (48 lines, 17 checks) — `normalize_release_name` on a battery of titles: generic CPI, institutional CPI variants, U Mich, NY Fed, trimmed mean, HICP, PCE, PPI, import prices, low-confidence fallback.
- **test_scope_reset.py** (232 lines, 92 checks) — `default_catalogue_country` per scope; `_SCOPE_RESET_KEYS` coverage (clears tab-local, preserves sidebar/global); `_reset_state_for_scope` clears, preserves, pre-seeds catalogue; PM scopes don't seed `cc_country`; `main()` wires `_handle_scope_change` before `st.tabs()`; `_handle_scope_change` short-circuits on unchanged scope.
- **test_weekly.py** (148 lines, 16 checks) — `find_data_windows` finds both windows in a multi-week file; `extract_blocks` splits into one Block per window; sub-blocks get correct windows; weekly releases extracted (no day-header rows); `block_data_window` infers from dates when no explicit window; `split_block_by_data_window` no-op without markers; streamlit_app imports.

---

## Files not part of the runtime

- `smoke_test.py` (root) — older standalone smoke test that pre-dates `tests/`. Builds synthetic DM/EUR weekly files, exercises `extract_blocks`, `extract_releases`, `filter_releases`, `parse_command`, theme detection, country extraction. Still works but largely superseded by `tests/`.
- `README.md` — run instructions and smoke-test invocation.
- `requirements.txt` — pinned deps.
- `.streamlit/config.toml` — Streamlit theme/server config.
- `data/cache/` — runtime-populated GitHub cache (gitignored).

---

## Notes for the auditor

1. **Pure vs. impure split.** Anything under `core/` and `utils/text.py` is pure and synchronously tested. `streamlit_app.py` and `core/render.py` are the only Streamlit-coupled modules. `core/loaders.py` and `utils/github.py` are the only network/filesystem modules.

2. **Source priority is enforced in two places.** (a) `sources_for_country` builds the allow-list with frozen-first ordering. (b) `dedup_releases` keeps the first occurrence by `release_key`. Together they guarantee frozen wins over live for duplicate events.

3. **Scope is global state.** `_handle_scope_change` is the only correct way to drop tab-local widget state when the user flips scope. Any new tab-local widget key must be added to `_SCOPE_RESET_KEYS`.

4. **Title parsing is the riskiest area.** `_looks_like_title_line` + `_looks_like_commentary_fragment` are the gates that decide what becomes a `Release`. Regressions here surface as commentary fragments showing up as releases in the catalogue. The `tests/test_catalogue_sources.py` and `tests/test_country.py` suites lock these.

5. **Dates are best-effort.** `parse_release_date` uses heuristics for `dd/mm` vs `mm/dd`. Anything that can't be parsed sorts to `date.min` and is dropped from `since/until` filtering rather than silently misplaced.

6. **OneDrive truncation pattern.** The repo lives on OneDrive; in-process `Edit`/`Write` operations have intermittently truncated files mid-content during this build. If review finds an obviously incomplete function, check whether the file is truncated on disk before assuming a logic bug.
