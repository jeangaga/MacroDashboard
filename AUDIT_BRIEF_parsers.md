# Audit brief — `core/parsers.py`

Third file in the audit pass. This is the parser that turns a raw archive
file into `Block`s and then into `Release`s. Two earlier audits already
flagged that:

1. **Title-vs-commentary heuristics are the riskiest area.** A regression
   here surfaces as commentary fragments showing up as releases in the
   catalogue.
2. **`Release` has no reference-period field.** Audit #2 wants a
   `reference_period` populated from the title (e.g. `(Mar)`, `(Q1)`,
   `(Mar/Feb)`) and used downstream by `release_key` and the catalogue.

Please address those two head-on, then broader review.

---

## Open questions inherited from earlier audits

1. **Where should `extract_reference_period` live?** Two reasonable spots:
   - In `utils/text.py` next to `parse_release_date` and `release_type`,
     called from `extract_releases` to populate `Release.reference_period`.
   - In `core/normalize.py` as part of the catalogue contract.

   Our preference is `utils/text.py` (pure text helper, no scope
   awareness), but flag if you disagree.

2. **What signals should it draw from?** The candidates we see in the
   archive:
   - Period suffix in the title: `(Mar)`, `(Q1)`, `(Mar/Feb)`, `(Apr P)`,
     `(2026)`, `Final YY`, `Advance`.
   - The release date (`r.date_str`) — useful for inferring the year when
     the title only carries a month.
   - The block's `data_window` start/end — useful when the title is bare
     (e.g. `Jobless Claims`).

   How does the function disambiguate `(Mar)` released on `2026-04-15`
   (clearly Mar 2026) vs released on `2026-01-08` (Mar 2025)? Year-rollover
   heuristic, or refuse to guess and return `None`?

3. **`Release` is a frozen dataclass.** Adding a field means migrating every
   call-site (smoke_test, tests, render). Worth doing in one shot, or do you
   recommend a separate `ReleaseMeta` namespace and leaving `Release`
   stable?

4. **`extract_releases` is 110 lines and has six implicit states**
   (`pending_preamble`, `current`, `promoted`, group consolidation, day-header
   peeling, structured-signal validation). Is the algorithm correct as
   written, and is there a cleaner small-state-machine refactor?

5. **`_TITLE_DASH_RE`** is `\S\s+[-\u2013\u2014]+\s+\S` — does it false-positive
   on titles that happen to contain dashes mid-sentence (e.g.
   `Banxico - 50bp cut as expected`)?

6. **`_looks_like_commentary_fragment`** uses prose heuristics
   (`> 110 chars`, `> 16 words`, no `/`, no dash, no country). Are those
   thresholds too aggressive — would they kill legitimate long titles like
   `Eurozone - Flash Composite PMI / Manufacturing PMI / Services PMI`?
   (We have a `/` clause guard, but only one.)

---

## File purpose

Two-layer parser:

1. `extract_blocks(text, source_file)` — splits a file by
   `<<STEM_BEGIN>>...<<STEM_END>>` markers, then optionally splits each
   block by inline `Data window:` headers (so a USD_WEEK file holding
   several weeks renders as one Block per week).
2. `extract_releases(block)` — splits a block into importance-flagged
   paragraphs, peels day-of-week banners, runs the title-vs-commentary
   guard, extracts country/themes/date, returns `list[Release]`.

Pure module (no Streamlit, no I/O). Imports `core.config` (for
`BLOCK_STEMS`, `MARKER_PREFIX`, `MARKER_SUFFIX`) and `utils.text` (for
`max_importance`, `country_from_title`, `detect_themes`, `first_date_string`,
`collapse_blank_lines`).

## Public API

| Symbol | Purpose |
|---|---|
| `Block` | Dataclass: `stem, source_file, raw_text, data_window, data_window_start, data_window_end`. Properties `region` and `kind`. |
| `Release` | Dataclass: `source_file, block_stem, region, kind, title, importance, date_str, countries, themes, raw_block`. Property `importance_rank`. **No `reference_period` field today.** |
| `extract_blocks(text, source_file, *, split_weekly=True)` | File → list of Block. |
| `extract_releases(block)` | Block → list of Release. |
| `find_data_windows(text)` | Returns `(label, start, end, match_start, match_end)` tuples for every `Data window:` header. |
| `split_block_by_data_window(block)` | Splits a Block by data-window headers. |
| `block_data_window(block)` | Returns `(label, start_date, end_date)`. Prefers explicit header; otherwise infers from min/max release dates. |
| `blocks_from_load_results(results)` / `releases_from_load_results(results)` | Convenience over `LoadResult` lists. |

## Where it's used

```
streamlit_app.py        : Block, Release, extract_blocks, extract_releases,
                          block_data_window, releases_from_load_results
core/render.py          : Block, Release, extract_releases (lazy import)
core/search.py          : Release (type only)
core/normalize.py       : Release (via release_key duck-typing -- not imported)
smoke_test.py           : extract_blocks, extract_releases
tests/test_*            : all of the above
```

The catalogue chronology fix (audit #1, audit #2) hinges on:
- adding `Release.reference_period` here,
- populating it inside `extract_releases`,
- consuming it in `core.normalize.release_key` (next file).

## Risk hot zones inside this file

### A. The title heuristic stack (lines 263-364)

Three layered guards decide what becomes a release title:

```python
_TITLE_SKIP_PREFIXES   # explicit "this is metadata, not a title"
_COMMENTARY_PREFIXES   # "for the regional story", "false dawn", ...
_NARRATIVE_PHRASES     # " matters because ", " driven by ", ...

def _looks_like_commentary_fragment(line):
    s = (line or "").strip()
    low = s.lower()
    for p in _COMMENTARY_PREFIXES:
        if low.startswith(p):
            return True
    has_dash_structure = _TITLE_DASH_RE.search(s) is not None
    has_country = bool(country_from_title(s))
    if not has_dash_structure and not has_country:
        for ph in _NARRATIVE_PHRASES:
            if ph in low:
                return True
        word_count = len(s.split())
        if len(s) > 110 and word_count > 16 and "/" not in s:
            return True
    return False

def _looks_like_title_line(line):
    # day-header? skip prefix? > 220 chars? commentary fragment?
    ...
```

Audit hazard: any new commentary phrase the analyst writes can leak
through, and any legitimate long title (slash-list of indicators) can be
killed. The thresholds are hand-tuned.

### B. The release-extraction state machine (lines 384-494)

```python
def extract_releases(block):
    paragraphs = _PARAGRAPH_SPLIT.split(block.raw_text)
    groups = []
    current = None
    pending_preamble = None
    for para in paragraphs:
        # 1. drop pure day-header paragraphs
        # 2. peel mixed day-header + content paragraphs
        # 3. if paragraph has importance flag:
        #      a. consider promoting the previous paragraph as preamble
        #      b. flush previous group
        #      c. start a new group with [preamble?, current_para]
        # 4. else:
        #      a. if no current group: stash as pending_preamble (if it looks like one)
        #      b. else: append to current group as commentary
    # flush final group, then validate each group has a structured release signal
```

`_has_release_signals(text)` is the validator that throws away blocks that
look like commentary stubs (no `Release Date:`, no `Importance:`, no
country-dashed title).

### C. Stem → region mapping (lines 64-93)

`_stem_to_region` and `_stem_to_kind` are suffix-stripping. Edge case:
`SHORT_WEEK` is in `_SHARED_STEMS` so its `region` is `""`, but its `kind`
is `frozen_week`. Whether the catalogue treats `SHORT_WEEK` as a frozen
source is determined by `country_source_status` in `core/config.py`, which
uses the suffix `_WEEK.txt` -> `frozen`. They're not coupled in code.

### D. Markerless files (lines 119-121)

```python
if not blocks:
    stem = _stem_from_filename(source_file)
    blocks = [Block(stem=stem, source_file=source_file, raw_text=text)]
```

A file with no markers becomes one big block whose stem is derived from
the filename. That keeps `block.region` working for files that haven't been
marked up yet, but means the data-window splitter is the only thing that
chunks them.

### E. `block_data_window` re-runs `extract_releases` (lines 538-540)

When a block has no explicit `Data window:` header, this function calls
`extract_releases(block)` *just to read the dates*. That's potentially
expensive on long files and not memoized. If the catalogue ever calls
`block_data_window` per-block, we'll be doing the parse twice.

### F. `_DATA_WINDOW_RE` end-of-line anchor

```python
_DATA_WINDOW_RE = re.compile(
    r"(?im)^[ \t]*data[ \t]*window[ \t]*[:\u2013\u2014-][ \t]*"
    r"(.+?)\s+(?:to|\u2013|\u2014|-)\s+(.+?)[ \t]*$"
)
```

The `?` lazy quantifiers + `$` mean a single line. Fine, but if a future
note breaks the window across two lines (`Data window: 13 Apr 2026\n  to 17 Apr 2026`), it won't match. Worth tightening or leave alone?

---

## Existing test coverage

### `tests/test_weekly.py` (16 checks)
- `find_data_windows` finds two windows in a multi-week file.
- `extract_blocks(split_weekly=True)` returns one Block per window.
- Sub-blocks carry the right `data_window` / `data_window_start` / `data_window_end`.
- Releases from each sub-block contain real titles, no `MONDAY 13 APR 2026`.
- `block_data_window` infers from release dates when explicit window is absent.
- Day-header-only blocks emit zero releases.
- `split_block_by_data_window` is a no-op without markers.

### `tests/test_catalogue_sources.py` (109 checks)
- End-to-end: synthetic block with intermixed real releases + commentary
  ("For the regional story...", "False dawn / rebound from collapse...")
  parses ONLY the real releases.

### `tests/test_country.py` (19 checks)
- Country aliasing word boundaries don't false-match (`US` not in `BUSINESS`).
- NFP rule is specific (UK HMRC Payrolls ≠ NFP).

### `tests/test_dedup.py` (10 checks)
- Day-header-only blocks emit zero releases (regression guard).
- Block construction with explicit raw_text works.

### `tests/test_macro_notes.py` (27 checks)
- Marker-delimited macro note files parse into multiple blocks when
  multiple `Data window:` sections appear.

---

## Full source

```python
"""
Marker-based parsing of the macro archive.

Two layers:
  1. extract_blocks(text, source_file) splits a file by <<STEM_BEGIN>>/<<STEM_END>>.
  2. extract_releases(block) splits a block into importance-flagged paragraphs.

Both preserve raw text. Both fail gracefully on odd input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from core.config import BLOCK_STEMS, MARKER_PREFIX, MARKER_SUFFIX
from utils.text import (
    collapse_blank_lines,
    country_from_title,
    detect_themes,
    first_date_string,
    max_importance,
)


@dataclass
class Block:
    stem: str
    source_file: str
    raw_text: str
    data_window: Optional[str] = None
    data_window_start: Optional[str] = None
    data_window_end: Optional[str] = None

    @property
    def region(self) -> str:
        return _stem_to_region(self.stem)

    @property
    def kind(self) -> str:
        return _stem_to_kind(self.stem)


_KNOWN_SCOPES = {
    "USD", "EUR", "DM", "EM",
    "AUD", "BRL", "CAD", "CHF", "CNH", "GBP", "INR", "JPY", "KRW",
    "MXN", "NOK", "PLN", "SEK", "TRY", "TWD", "ZAR",
}

_SHARED_STEMS = {"WEEKPM", "MACROPM", "SHORT_WEEK", "ARC"}


def _all_known_stems():
    seen = set()
    out = []
    for stems in BLOCK_STEMS.values():
        for s in stems:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _stem_to_region(stem: str) -> str:
    s = stem.upper()
    if s in _SHARED_STEMS:
        return ""
    for suffix in ("_WEEK_LIVE_MACRO", "_WEEK_PM_STYLE", "_MACRO_NOTE", "_WEEK"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s == "US":
        return "USD"
    if s in _KNOWN_SCOPES:
        return s
    return s


def _stem_to_kind(stem: str) -> str:
    s = stem.upper()
    if s.endswith("_WEEK_LIVE_MACRO"):
        return "live_week"
    if s.endswith("_WEEK_PM_STYLE") or s in {"WEEKPM", "MACROPM"}:
        return "pm_style"
    if s.endswith("_MACRO_NOTE"):
        return "macro_note"
    if s == "SHORT_WEEK":
        return "frozen_week"
    if s == "ARC":
        return "pm_style"
    if s.endswith("_WEEK"):
        return "frozen_week"
    return "unknown"


def _marker_regex(stem):
    begin = re.escape(MARKER_PREFIX + stem + "_BEGIN" + MARKER_SUFFIX)
    end = re.escape(MARKER_PREFIX + stem + "_END" + MARKER_SUFFIX)
    return re.compile(begin + r"\s*(.*?)\s*" + end, re.DOTALL)


def extract_blocks(text: str, source_file: str, *, split_weekly=True):
    """Split a file's text into Blocks.

    First pass uses the <<STEM_BEGIN>>/<<STEM_END>> markers. If `split_weekly`
    is True, each block that contains "Data window: ..." headers is further
    split into one sub-block per window (so a USD_WEEK file holding several
    weeks renders as one card per week).
    """
    if not text:
        return []
    blocks = []
    for stem in _all_known_stems():
        pat = _marker_regex(stem)
        for m in pat.finditer(text):
            inner = m.group(1)
            if inner.strip():
                blocks.append(Block(stem=stem, source_file=source_file, raw_text=inner))
    if not blocks:
        stem = _stem_from_filename(source_file)
        blocks = [Block(stem=stem, source_file=source_file, raw_text=text)]
    if not split_weekly:
        return blocks
    expanded = []
    for b in blocks:
        expanded.extend(split_block_by_data_window(b))
    return expanded


def _stem_from_filename(filename: str) -> str:
    base = filename.rsplit("/", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.upper()


@dataclass
class Release:
    source_file: str
    block_stem: str
    region: str
    kind: str
    title: str
    importance: Optional[str]
    date_str: Optional[str]
    countries: list = field(default_factory=list)
    themes: list = field(default_factory=list)
    raw_block: str = ""

    @property
    def importance_rank(self) -> int:
        return len(self.importance) if self.importance else 0


_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")

# Day-of-week banners we want to strip (e.g. "MONDAY 13 APR 2026" or
# "TUESDAY 06 JAN 2026 - RELEASED"). They are section dividers, not releases.
_DAY_HEADER_RE = re.compile(
    r"^\s*(?:MON|TUE|WED|THU|FRI|SAT|SUN)[A-Z]*DAY\s+"
    r"\d{1,2}\s+"
    r"[A-Z]{3,9}\s+"
    r"\d{4}"
    r"(?:\s*[-\u2013\u2014]\s*RELEASED)?\s*$",
    re.I,
)

# A "Data window: <start> to <end>" header.
_DATA_WINDOW_RE = re.compile(
    r"(?im)^[ \t]*data[ \t]*window[ \t]*[:\u2013\u2014-][ \t]*"
    r"(.+?)\s+(?:to|\u2013|\u2014|-)\s+(.+?)[ \t]*$"
)

# Lines that prove this paragraph carries real release content.
_RELEASE_FIELD_RE = re.compile(
    r"(?im)^\s*(?:release\s+date|importance|reuters\s+data|actual|prior|previous|consensus|poll|forecast)\s*[:\u2013\u2014-]",
)

# Country-prefixed title pattern: "United States - CPI", "US - Retail Sales".
_TITLE_DASH_RE = re.compile(r"\S\s+[-\u2013\u2014]+\s+\S")


def _is_day_header_line(line):
    return bool(_DAY_HEADER_RE.match((line or "").strip()))


def _is_day_header_paragraph(paragraph):
    if not paragraph:
        return False
    meaningful = [ln.strip() for ln in paragraph.splitlines() if ln.strip()]
    if not meaningful:
        return False
    return all(_is_day_header_line(ln) for ln in meaningful)


def _strip_day_header_lines(paragraph):
    if not paragraph:
        return paragraph
    kept = [ln for ln in paragraph.splitlines() if not _is_day_header_line(ln)]
    return "\n".join(kept).strip("\n")


def _has_release_signals(text):
    """True iff `text` contains at least one structured release field
    (Release Date, Importance, Actual, Prior, Reuters Data, etc.) OR a
    country-prefixed dashed title."""
    if not text:
        return False
    if _RELEASE_FIELD_RE.search(text):
        return True
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _is_day_header_line(line):
            continue
        if _TITLE_DASH_RE.search(line) and country_from_title(line):
            return True
        break
    return False


def find_data_windows(text):
    """Return list of (label, start, end, match_start, match_end) tuples for
    each "Data window: X to Y" header in `text`, in document order."""
    if not text:
        return []
    out = []
    for m in _DATA_WINDOW_RE.finditer(text):
        start = m.group(1).strip().rstrip(",;.")
        end = m.group(2).strip().rstrip(",;.")
        label = f"{start} to {end}"
        out.append((label, start, end, m.start(), m.end()))
    return out


def split_block_by_data_window(block):
    """If `block.raw_text` contains "Data window:" markers, split into one
    Block per window. Otherwise return [block] unchanged."""
    if not block or not block.raw_text:
        return [block]
    windows = find_data_windows(block.raw_text)
    if not windows:
        return [block]
    out = []
    for i, (label, start, end, ms, me) in enumerate(windows):
        seg_start = ms
        seg_end = windows[i + 1][3] if i + 1 < len(windows) else len(block.raw_text)
        chunk = block.raw_text[seg_start:seg_end].strip()
        if not chunk:
            continue
        out.append(Block(
            stem=block.stem,
            source_file=block.source_file,
            raw_text=chunk,
            data_window=label,
            data_window_start=start,
            data_window_end=end,
        ))
    return out or [block]


# Lines we never want to use as a release title.
_TITLE_SKIP_PREFIXES = (
    "release date",
    "local time",
    "importance",
    "reuters data",
    "economist layer",
    "hf take",
    "signal tension",
    "consensus",
    "previous",
    "actual",
    "data window",
)

# Commentary-fragment markers: when a candidate title starts with one of these
# phrases it's narrative text from an Economist Layer / HF Take block, not a
# real release header. Lower-cased prefix match.
_COMMENTARY_PREFIXES = (
    "for the regional story",
    "for the bigger picture",
    "for the headline story",
    "this matters because",
    "this is why",
    "the regional story",
    "the bigger picture",
    "the headline story",
    "the read-through",
    "the read through",
    "the takeaway",
    "the take-away",
    "what this means",
    "what to watch",
    "key takeaways",
    "in summary",
    "bottom line",
    "false dawn",
    "rebound from collapse",
    "miss vs consensus",
    "beat vs consensus",
    "domestic weakness",
    "foreign-led only",
    "the question is",
    "looking ahead",
)

# Narrative phrases that strongly suggest a sentence is prose commentary,
# not a release header.
_NARRATIVE_PHRASES = (
    " matters because ",
    " is too large to absorb ",
    " driven by ",
    " offset by ",
    " owing to ",
    " on the back of ",
    " in line with ",
    " consistent with ",
    " suggests that ",
    " implies that ",
)


def _looks_like_commentary_fragment(line):
    """True when the line looks like prose / commentary, not a release title."""
    s = (line or "").strip()
    if not s:
        return False
    low = s.lower()
    for p in _COMMENTARY_PREFIXES:
        if low.startswith(p):
            return True
    has_dash_structure = _TITLE_DASH_RE.search(s) is not None
    has_country = bool(country_from_title(s))
    if not has_dash_structure and not has_country:
        for ph in _NARRATIVE_PHRASES:
            if ph in low:
                return True
        word_count = len(s.split())
        if len(s) > 110 and word_count > 16 and "/" not in s:
            return True
    return False


def _looks_like_title_line(line):
    s = (line or "").strip()
    if not s:
        return False
    if _is_day_header_line(s):
        return False
    low = s.lower()
    for p in _TITLE_SKIP_PREFIXES:
        if low.startswith(p):
            return False
    if len(s) > 220:
        return False
    if _looks_like_commentary_fragment(s):
        return False
    return True


def _looks_like_preamble(paragraph):
    if not paragraph:
        return False
    line = ""
    for raw in paragraph.splitlines():
        if raw.strip():
            line = raw.strip()
            break
    if not _looks_like_title_line(line):
        return False
    if any(sep in line for sep in (" \u2014 ", " \u2013 ", " - ", " -- ")):
        return True
    if country_from_title(line):
        return True
    return len(line) <= 120


def extract_releases(block):
    """Split a block into releases.

    A release starts at a paragraph containing an importance flag.
    All subsequent un-flagged paragraphs are commentary.

    Day headers ("MONDAY 13 APR 2026") are stripped before grouping so they
    never become release titles. Groups without any structured release signal
    (Release Date / Importance / Actual / Prior / country-dash title) are
    discarded.
    """
    if not block or not block.raw_text:
        return []
    paragraphs = _PARAGRAPH_SPLIT.split(block.raw_text)

    groups = []
    current = None
    pending_preamble = None

    for para in paragraphs:
        para = para.strip("\n")
        if not para.strip():
            continue
        if _is_day_header_paragraph(para):
            continue
        if any(_is_day_header_line(ln) for ln in para.splitlines()):
            stripped = _strip_day_header_lines(para)
            if not stripped.strip():
                continue
            para = stripped
        flag = max_importance(para)
        if flag is not None:
            promoted = None
            if (
                current is not None
                and len(current) >= 2
                and max_importance(current[-1]) is None
                and _looks_like_preamble(current[-1])
            ):
                promoted = current.pop()
            if current is not None:
                groups.append(current)
            if promoted is not None:
                current = [promoted, para]
            elif pending_preamble is not None:
                current = [pending_preamble, para]
            else:
                current = [para]
            pending_preamble = None
        else:
            if current is None:
                if _looks_like_preamble(para):
                    pending_preamble = para
                else:
                    pending_preamble = None
                continue
            current.append(para)

    if current is not None:
        groups.append(current)

    releases = []
    region = block.region
    kind = block.kind
    for group in groups:
        first = group[0]
        first_flag = max_importance(first)
        if first_flag is None:
            title_source = first
            header_for_flag = group[1] if len(group) > 1 else first
        else:
            title_source = first
            header_for_flag = first

        flag = max_importance(header_for_flag)
        full_text = "\n\n".join(group)

        if not _has_release_signals(full_text):
            continue

        title = _best_title_line(title_source)
        if not title:
            for para in group:
                cand = _best_title_line(para)
                if cand:
                    title = cand
                    break

        if title and _is_day_header_line(title):
            continue

        date_str = first_date_string(full_text)
        countries = country_from_title(title)
        themes = detect_themes(full_text)
        releases.append(Release(
            source_file=block.source_file,
            block_stem=block.stem,
            region=region,
            kind=kind,
            title=_clean_title(title),
            importance=flag,
            date_str=date_str,
            countries=countries,
            themes=themes,
            raw_block=collapse_blank_lines(full_text),
        ))
    return releases


def _best_title_line(paragraph):
    if not paragraph:
        return ""
    for raw in paragraph.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _looks_like_title_line(line):
            return line
    return ""


def _first_meaningful_line(text):
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _clean_title(title):
    t = re.sub(r"\s*\|\s*\*{1,4}\s*$", "", title or "").strip()
    t = re.sub(r"\s*\*{1,4}\s*$", "", t).strip()
    return t[:180]


def block_data_window(block):
    """Return (label, start_date, end_date) for a block.

    Prefers the explicit "Data window:" header. If none, infers from the
    earliest/latest parsed release dates inside the block. Returns
    (label, None, None) when nothing is available.
    """
    from utils.text import parse_release_date

    if block is None:
        return ("", None, None)
    if block.data_window:
        s = parse_release_date(block.data_window_start) if block.data_window_start else None
        e = parse_release_date(block.data_window_end) if block.data_window_end else None
        return (block.data_window, s, e)
    rels = extract_releases(block)
    dates = [parse_release_date(r.date_str) for r in rels if r.date_str]
    dates = [d for d in dates if d is not None]
    if not dates:
        return ("", None, None)
    s = min(dates)
    e = max(dates)
    label = f"{s.strftime('%d %b %Y')} to {e.strftime('%d %b %Y')}"
    return (label, s, e)


def blocks_from_load_results(results):
    out = []
    for r in results:
        if not r.text:
            continue
        out.extend(extract_blocks(r.text, source_file=r.filename))
    return out


def releases_from_load_results(results):
    out = []
    for blk in blocks_from_load_results(results):
        out.extend(extract_releases(blk))
    return out
```

---

## What we'd specifically like ChatGPT to look for

1. **Reference-period extraction.** Sketch what
   `extract_reference_period(title, raw_block, release_date) -> Optional[str]`
   should return for these archive cases:
   ```
   "United States - CPI (Mar)"                                   -> "2026-03"
   "United States - Retail Sales MM (Mar)"                       -> "2026-03"
   "Eurozone - HICP Final YY"                                    -> ???
   "Australia - GDP (Q1)"                                        -> "2026-Q1"
   "Australia - Trimmed Mean CPI (Q1) - YoY"                     -> "2026-Q1"
   "US - PCE / Core PCE"                                         -> ???
   "US - Jobless Claims"                                         -> derive from release_date week
   "US - U Mich Sentiment Final (Apr)"                           -> "2026-04" (Final qualifier irrelevant?)
   "US - PPI Final Demand (Apr P)"                               -> "2026-04" (P = preliminary)
   ```
   Recommend a return shape (string vs `(year, period_label)` tuple) and
   year-rollover policy.

2. **Where to call it.** Inside `extract_releases`, after `date_str` is
   resolved? Or as a deferred property on `Release`?

3. **Title-vs-commentary heuristics.** Are the thresholds in
   `_looks_like_commentary_fragment` (110 chars, 16 words, no `/`, no dash,
   no country) defensible? Suggest concrete failure cases.

4. **State-machine refactor.** The 110-line `extract_releases` body has 6+
   implicit states. Is there a cleaner refactor that's still test-equivalent?

5. **`_DATA_WINDOW_RE`.** Single-line only. Should it tolerate a wrapped
   `Data window:` line, or is it fine to leave strict?

6. **`block_data_window` re-runs `extract_releases`.** Worth memoizing on
   the Block, or YAGNI?

7. **`_TITLE_DASH_RE = \S\s+[-\u2013\u2014]+\s+\S`** — too permissive?

8. **`_stem_to_region` corner case.** For a stem like `EUR_WEEK_PM_STYLE`,
   the loop strips `_WEEK_PM_STYLE` first and returns `EUR`. Good. For
   `WEEKPM` it returns `""` because it's in `_SHARED_STEMS`. The catalogue
   code never hits this path directly (it filters by file, not by stem),
   but if anyone reads `block.region` on a `WEEKPM` block they'll get an
   empty string. Worth defending or documenting?

Don't propose new files yet — give us the textual recommendations and we
will translate to code.
