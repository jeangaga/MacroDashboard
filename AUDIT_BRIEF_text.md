# Audit brief — `utils/text.py`

Fourth file in the audit pass. This is the small text-utility layer: importance
detection, country/theme tagging, date parsing, release-type stripping. Every
module above it (`core/parsers.py`, `core/normalize.py`, `core/search.py`,
`core/render.py`, `streamlit_app.py`, every test) calls into this file.

Audit #3 explicitly proposed adding two new helpers here:

- `release_date_string(full_text)` — prioritizes `Release Date:` line over
  any other date in the block.
- `extract_reference_period(title, raw_block, release_date)` — returns the
  reference period the release describes (e.g. `2026-03`, `2026-Q1`).

Both belong here because they're pure text helpers with no scope or
file-format awareness. Audit them in this context.

---

## Open questions inherited from earlier audits

1. **`release_date_string(full_text)` — exact behaviour?** Audit #3 wants:
   ```
   Order of precedence:
     (a) "Release Date: YYYY-MM-DD" / "Release Date: 21 Apr 2026" line
     (b) "Local Time: ..." date line
     (c) first_date_string(full_text) fallback
   Avoid: "Data window: 13 Apr 2026 to 17 Apr 2026" (this is the WINDOW, not the release)
   ```
   What's the cleanest way to express "skip dates that appear on a `Data
   window:` line"? Strip those lines first, or use a label-anchored regex?

2. **`extract_reference_period(title, raw_block, release_date)` — return shape?**
   Worked examples we expect to handle:
   ```
   "United States - CPI (Mar)"                     -> "2026-03"
   "United States - Retail Sales MM (Mar)"         -> "2026-03"
   "Eurozone - HICP Final YY"                      -> ???   (YY is "year over year", not a period)
   "Australia - GDP (Q1)"                          -> "2026-Q1"
   "Australia - Trimmed Mean CPI (Q1) - YoY"       -> "2026-Q1"
   "US - PCE / Core PCE"                           -> ???   (no period, infer from release_date?)
   "US - Jobless Claims"                           -> WEEK starting (release_date - 7d)?
   "US - U Mich Sentiment Final (Apr)"             -> "2026-04"
   "US - PPI Final Demand (Apr P)"                 -> "2026-04"
   "US - PPI Final Demand (Apr F)"                 -> "2026-04"  (P=preliminary, F=final, both refer to Apr)
   "US - Empire Manufacturing (May)"               -> "2026-05"
   "US - NFP (Mar/Feb revision)"                   -> "2026-03"  (latest period wins)
   ```
   Do you prefer a string label (`"2026-03"` / `"2026-Q1"` / `"2026-W17"`)
   or a `(year, granularity, n)` tuple where `granularity ∈ {month, quarter, week}`?

3. **Year-rollover.** A release published `2026-01-08` reporting `(Dec)` is
   plainly `2025-12`. Heuristic: if the parenthesized month is greater than
   `release_date.month`, subtract a year. Acceptable, or too clever?

4. **`parse_release_date` for dd/mm vs mm/dd.** Today the heuristic is "if the
   first number > 12, assume DD/MM/YYYY, else assume MM/DD/YYYY." That
   silently mis-parses `01/04/2026` (April 1 in Europe, Jan 4 in the US) as
   January 4. Should we make the policy configurable, or pass a hint from
   the call-site (e.g. region of the source file)?

5. **`first_date_string` returns the *first* date in textual order.** That's
   why audit #3 flagged this — if `Data window: 20 Apr 2026 to 24 Apr 2026`
   appears before `Release Date: 21 Apr 2026`, we currently store
   `"20 Apr 2026"` as the release date. Should `first_date_string` learn to
   skip lines starting with `Data window:`, or should we leave it dumb and
   put the smarts in `release_date_string`?

6. **`release_type` strips parentheses.** `"US - CPI (Mar)" -> "CPI"`. That
   was correct for normalization, but **destroys the period information we
   now need**. We'll need either (a) a sibling `release_period_token(title)`
   helper that returns just the parenthesized period, or (b) make
   `release_type` return both. Recommend the cleanest split.

7. **`detect_countries` vs `country_from_title`.** Audit #3 (point 1) wants
   `country_from_title(title) or detect_countries(full_text)` as the
   fallback. But `detect_countries` scans freely and can match an alias
   buried in commentary. Should we restrict it to lines starting with
   `Country:` or appearing inside the first 3 lines of the block?

---

## File purpose

Pure text helpers. Imports `core.config` for theme/country/importance
constants. No filesystem, no network, no Streamlit.

## Public API

| Symbol | Purpose |
|---|---|
| `max_importance(text)` | Returns longest run of `*` (e.g. `"****"`) found anywhere in `text`, or `None`. |
| `importance_rank(flag)` | Returns numeric rank 0-4. |
| `detect_countries(text)` | Returns list of countries whose aliases match anywhere in `text`. Word-boundary matched. |
| `country_from_title(title)` | At most one country, scanned only on the first non-empty line of `title`. |
| `detect_themes(text)` | Returns list of themes whose keywords match `text` (case-insensitive substring). |
| `first_date_string(text)` | Returns the first date string of any of 4 supported formats, or `None`. |
| `parse_release_date(text)` | Best-effort parse of `first_date_string(text)` to `datetime.date` or `None`. |
| `release_type(title)` | Strips country prefix, period parens, trailing date. `"United States - PPI Final Demand (Mar)"` -> `"PPI Final Demand"`. |
| `collapse_blank_lines(text)` | Collapses 3+ blank lines into 2. |
| `any_keyword(text, keywords)` | True if any keyword matches `text` (case-insensitive). |

## Where it's used

```
core/parsers.py    : max_importance, country_from_title, detect_themes,
                     first_date_string, collapse_blank_lines (and parse_release_date
                     in block_data_window via a deferred import)
core/normalize.py  : release_type
core/render.py     : collapse_blank_lines, importance_rank
core/search.py     : (date helpers + theme/country detection — see search.py audit)
streamlit_app.py   : parse_release_date  (used by _release_sort_key in catalogue!)
tests/*            : parse_release_date, country_from_title, detect_countries
```

The catalogue's "latest" decision flows through this file:

```python
# streamlit_app.py
def _release_sort_key(r):
    d = parse_release_date(r.date_str) or parse_release_date(r.raw_block)
    return d or _dt.date.min
```

So `parse_release_date` correctness is load-bearing for catalogue
chronology. If audit #3's `release_date_string` lands as a wrapper that
prioritizes `Release Date:`, the call-site fix is straightforward — but
the behaviour change has to be deliberate.

---

## Risk hot zones in this file

### A. `_IMPORTANCE_RE` matches stars anywhere

```python
_IMPORTANCE_RE = re.compile(r"(?<![\*\w])(\*{1,4})(?![\*\w])")
```

Word-boundary against word chars + asterisks. So `"the **** print"` matches
`****` but `"see *cm*"` does not. **Audit #3 flagged this** — a paragraph
that contains `****` in commentary will currently start a new release group
in `extract_releases`. Possible mitigations:
- Anchor to "after a `|` or end-of-line" (require `... | ****` or
  `Importance: ***`), or
- Two-stage detection: free-form for "this paragraph mentions importance"
  vs. line-anchored for "this is the importance flag".

### B. `_DATE_PATTERNS` can match revision dates

```python
_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})\b", re.I),
    re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}),?\s+(\d{4})\b", re.I),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
]
```

`first_date_string` returns the first match from any pattern. Order matters:
DD-MMM-YYYY before MMM-DD-YYYY before YYYY-MM-DD before DD/MM/YYYY. A
sentence "see also 13 Apr 2026 revision" inside commentary will be picked
up before the `Release Date:` line that follows.

### C. `release_type` destroys period info

`_PERIOD_PARENS = re.compile(r"\s*\([^)]*\)\s*$")` strips `(Mar)`,
`(Q1)`, `(Mar/Feb)`, `(Apr P)`. That's correct for normalization grouping,
but the catalogue chronology fix needs to *recover* what was inside the
parens. Either:
- Add `release_period_token(title)` that returns just the trailing parens
  contents, or
- Refactor `release_type` to return `(stripped_title, period_token)`.

### D. `parse_release_date`'s dd/mm heuristic

```python
m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
if m:
    a = int(m.group(1)); b = int(m.group(2)); c = int(m.group(3))
    if a > 12:
        return _dt.date(c, b, a)
    return _dt.date(c, a, b)
```

`01/04/2026` → April 1 in EU files, Jan 4 in US files. We pick US semantics.
For an EU-heavy archive this can silently mis-date.

### E. `country_from_title` returns at most one

By design — country tagging in the title is meant to be unambiguous. But
audit #3 wants a fallback to the body. If a title is something like `Joint
US-China Trade Statement`, both countries should arguably tag.

### F. `detect_themes` is substring, not word-boundary

```python
for kw in THEME_KEYWORDS[theme]:
    if kw.lower() in lower:
        hits.append(theme)
        break
```

Substring match, no word boundary. So `"PMI"` will match anywhere
`"pmi"` appears, including inside compound words. Worth tightening to
boundaries?

---

## Existing test coverage

### `tests/test_country.py` (19 checks)
- `country_from_title` returns `[]` for `"Bonus Day"`, `"USB Stocks"`.
- `country_from_title` returns `["US"]` for `"US - CPI"`, `"United States - NFP"`.
- `detect_countries` matches multiple countries in body text, e.g.
  `"US-China trade balance"` returns `["US", "China"]`.

### `tests/test_dedup.py` (10 checks)
- `parse_release_date("2026-04-21") == date(2026, 4, 21)` (used in
  catalogue grouping after dedup).

### `tests/test_catalogue.py` (catalogue smoke)
- `parse_release_date` exercised indirectly via the catalogue grouping
  logic.

No direct test currently covers:
- `parse_release_date("01/04/2026")` (the dd/mm pitfall).
- `first_date_string` returning a date inside `Data window:`.
- `release_type` against periods like `(Apr P)`, `(Q1)`, `(Mar/Feb)`.
- `max_importance` against asterisks inside commentary prose.

---

## Full source

```python
"""Text helpers: importance-flag detection, country/theme tagging, date detection."""
from __future__ import annotations

import calendar
import datetime as _dt
import re
from typing import Iterable, Optional

from core.config import (
    ALL_THEMES,
    COUNTRY_ALIASES,
    IMPORTANCE_LEVELS,
    THEME_KEYWORDS,
)

_IMPORTANCE_RE = re.compile(r"(?<![\*\w])(\*{1,4})(?![\*\w])")


def max_importance(text):
    if not text:
        return None
    best = 0
    for m in _IMPORTANCE_RE.finditer(text):
        n = len(m.group(1))
        if n > best:
            best = n
    if best == 0:
        return None
    return "*" * best


def importance_rank(flag):
    if not flag:
        return 0
    return len(flag) if flag in IMPORTANCE_LEVELS else 0


# ---------------------------------------------------------------------------
# Country aliasing
#
# Aliases are matched with word boundaries so that short codes like "US",
# "UK", "DE", "EA" do not false-match inside unrelated words. For example,
# the substring "us " appears inside "Bonus " — the old substring matcher
# wrongly tagged any release that mentioned "Bonus" as "US". The new matcher
# uses (?<!\w)<alias>(?!\w), which:
#
#   - matches "US" in "US Treasury" or "US " or "U.S." but NOT in "USD",
#     "BONUS", or "BUSINESS"
#   - matches "UK" in "United Kingdom — CPI" via the "United Kingdom" alias
#   - keeps multi-word aliases ("United States", "American") working
# ---------------------------------------------------------------------------

def _build_country_patterns():
    out = {}
    for country, aliases in COUNTRY_ALIASES.items():
        pats = []
        for alias in aliases:
            a = alias.strip()
            if not a:
                continue
            pat = re.compile(r"(?<!\w)" + re.escape(a) + r"(?!\w)", re.IGNORECASE)
            pats.append(pat)
        if pats:
            out[country] = pats
    return out


_COUNTRY_PATTERNS = _build_country_patterns()


def detect_countries(text):
    """Return all countries whose aliases match in `text`. Order = COUNTRY_ALIASES order."""
    if not text:
        return []
    out = []
    for country, patterns in _COUNTRY_PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                out.append(country)
                break
    return out


def country_from_title(title):
    """Tighter country detection: scan only the title/header line.

    Returns at most one country - the first alias hit on the first non-empty
    line of the title.
    """
    if not title:
        return []
    line = title.strip().splitlines()[0]
    for country, patterns in _COUNTRY_PATTERNS.items():
        for pat in patterns:
            if pat.search(line):
                return [country]
    return []


def detect_themes(text):
    if not text:
        return []
    lower = text.lower()
    hits = []
    for theme in ALL_THEMES:
        for kw in THEME_KEYWORDS[theme]:
            if kw.lower() in lower:
                hits.append(theme)
                break
    return hits


_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{4})\b", re.I),
    re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}),?\s+(\d{4})\b", re.I),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
]


def first_date_string(text):
    if not text:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


_MONTH_ABBR = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def parse_release_date(text):
    """Best-effort parse of the first date in `text` to datetime.date, or None."""
    if not text:
        return None
    s = first_date_string(text)
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", s)
    if m:
        day, mon, year = m.groups()
        mi = _MONTH_ABBR.get(mon[:3].lower())
        if mi:
            try:
                return _dt.date(int(year), mi, int(day))
            except ValueError:
                pass
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m:
        mon, day, year = m.groups()
        mi = _MONTH_ABBR.get(mon[:3].lower())
        if mi:
            try:
                return _dt.date(int(year), mi, int(day))
            except ValueError:
                pass
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        a = int(m.group(1)); b = int(m.group(2)); c = int(m.group(3))
        try:
            if a > 12:
                return _dt.date(c, b, a)
            return _dt.date(c, a, b)
        except ValueError:
            return None
    return None


_PERIOD_PARENS = re.compile(r"\s*\([^)]*\)\s*$")
_TRAILING_DATE = re.compile(
    r"\s*[-\u2013\u2014]\s*"
    r"(?:\d{1,2}\s+[A-Za-z]+\s+\d{4}"
    r"|[A-Za-z]+\s+\d{1,2},?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{4})"
    r"\s*$"
)
_SEPARATORS = (" \u2014 ", " \u2013 ", " - ", " -- ")


def release_type(title):
    """Strip country prefix / period / trailing date so that
    'United States - PPI Final Demand (Mar)' -> 'PPI Final Demand'.
    """
    if not title:
        return ""
    t = title.strip()
    t = _TRAILING_DATE.sub("", t)
    t = _PERIOD_PARENS.sub("", t).strip()
    for sep in _SEPARATORS:
        if sep in t:
            t = t.split(sep, 1)[1].strip()
            break
    t = _PERIOD_PARENS.sub("", t).strip()
    return t


def collapse_blank_lines(text):
    if not text:
        return text
    return re.sub(r"\n{3,}", "\n\n", text)


def any_keyword(text, keywords):
    if not text:
        return False
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)
```

---

## What we'd specifically like ChatGPT to look for

1. **`release_date_string(full_text)` design.** Recommend the exact regex
   strategy. We want it to:
   - Prefer a line starting with `Release Date:` (or
     `Local Time:` followed by a date).
   - Skip dates that appear on `Data window:` lines.
   - Fall back to `first_date_string` only when no labelled date exists.
   Sketch the function. Where should it live (here or in `core/parsers.py`)?

2. **`extract_reference_period(title, raw_block, release_date)` design.**
   Address the worked examples in the open-questions section. Recommend
   return shape (string label vs structured tuple). State explicitly what
   happens when no period can be inferred.

3. **`release_type` refactor.** It currently destroys parens. Propose either
   a sibling helper or a tuple return. Don't break the existing
   `tests/test_normalize.py` assertions.

4. **dd/mm vs mm/dd policy.** Should the call-site pass a region hint? Or
   should `parse_release_date` accept an explicit `dayfirst=True/False` kwarg?

5. **`max_importance` brittleness.** Audit #3 wants importance detection
   confined to `Importance: ***` lines or title-suffix `| ***`. Sketch the
   tightest pattern that doesn't break existing test fixtures.

6. **`detect_themes` substring matching.** Worth switching to word-boundary?
   Concrete failure cases?

7. **`detect_countries` as fallback.** When `country_from_title` returns
   `[]`, should we fall back to `detect_countries` over the FIRST N lines
   of the block (not the whole block)? What's a safe N?

8. **Anything else missing.** New text helpers we should add now while
   we're refactoring this layer (e.g. `is_weekly_release(title)`,
   `is_quarterly_release(title)`)?

Don't propose new files — we'll translate to code after all audits are in.
