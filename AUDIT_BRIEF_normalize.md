# Audit brief — `core/normalize.py`

Second file in the audit pass. The previous audit on `streamlit_app.py`
already raised concerns that land squarely in this module — please answer
those head-on before broader review.

## Open questions inherited from audit #1 (please address explicitly)

1. **Release date vs. reference period.** The catalogue currently picks
   "latest" by `release.date_str` (the publication date), so a delayed
   revision can outrank a fresh print for an earlier reference period. Should
   `normalize` expose an `extract_reference_period(title, raw_block, date_str)`
   helper, and should `release_key` become reference-period-based?

2. **`release_key` includes `importance`.** This means the same release with
   importance flipped between frozen and live (or between two different
   parses) will dedup to two rows in the catalogue. Should we either:
   (a) drop `importance` from the key, or (b) introduce a second
   `catalogue_key(release)` without importance, used only by the catalogue
   tab (Weekly Monitor / Theme Monitor would keep the strict key)?

3. **Country selection in `release_key`.** Today we use
   `release.countries[0]`. This is order-of-detection in the title — fine
   for single-country releases, ambiguous for multi-country headlines.
   Should we sort `countries` first, or is "first detected" good enough?

4. **Confidence as part of grouping.** `meta[name] = (theme, conf)` snapshots
   the FIRST occurrence's confidence. If a later occurrence has higher
   confidence (e.g. an institutional rule fires), we lose that. Worth fixing
   in `normalize`, or only in the caller?

5. **Coverage gaps.** Anything obvious missing from `_RULES`? In particular
   for: BoJ Tankan variants, EM-specific labour series, services PMI vs
   manufacturing PMI distinction, central-bank-by-name decisions ("Banxico
   Decision", "BCB Decision" etc.), housing-completion vs starts vs
   approvals.

---

## File purpose

Maps a free-form release title to a **canonical recurring release name**
plus a theme and a confidence flag. The normalizer is intentionally
conservative — when in doubt it keeps the cleaned original title (with
confidence `Low`) rather than collapsing unrelated releases.

It also exports the dedup helpers used by the catalogue and Weekly Monitor.

## Public API

| Symbol | Purpose |
|---|---|
| `normalize_release_name(title) -> (name, theme, confidence)` | The core mapping. Confidence is `High`/`Medium`/`Low`. |
| `is_known(title) -> bool` | True iff confidence is High or Medium. |
| `release_key(release) -> str` | Stable dedup key: `country|name|date|importance`. |
| `dedup_releases(releases) -> list` | Drops duplicates by `release_key`, keeping FIRST occurrence. |

## Where it's used

- `streamlit_app.py` line 29: `from core.normalize import dedup_releases, normalize_release_name, release_key`
- `streamlit_app.py` line 381 (Weekly Monitor): `releases = dedup_releases(releases)`
- `streamlit_app.py` lines 793, 798 (Country Release Catalogue):
  ```python
  country_releases = dedup_releases(country_releases)
  for r in country_releases:
      name, theme, conf = normalize_release_name(r.title)
  ```
- All four `tests/test_*.py` suites that touch normalization.

## Catalogue call-site (the one audit #1 flagged)

```python
# streamlit_app.py, tab_country_release_catalogue()
country_releases = dedup_releases(country_releases)

groups = {}
meta = {}
for r in country_releases:
    name, theme, conf = normalize_release_name(r.title)
    if not name:
        continue
    if only_known and conf == "Low":
        continue
    if theme_filter and theme not in theme_filter:
        continue
        continue                                      # <-- dead duplicate
    groups.setdefault(name, []).append(r)
    if name not in meta:
        meta[name] = (theme, conf)                    # <-- confidence frozen at first

rows = []
for name, rels in groups.items():
    rels_sorted = sorted(rels, key=_release_sort_key, reverse=True)
    latest = rels_sorted[0]                           # <-- "latest" = release date
    ...
    rows.append({
        ...
        "Latest date": latest.date_str or "-",
        ...
    })

# _release_sort_key is defined as:
def _release_sort_key(r):
    d = parse_release_date(r.date_str) or parse_release_date(r.raw_block)
    return d or _dt.date.min
```

So `latest` is whichever block has the largest *publication* date. The
catalogue never sees a "reference period" anywhere.

## Existing test coverage

### `tests/test_normalize.py` (17 checks)

Pure title→tuple assertions. Examples:

```
US - CPI (Mar)                              -> ("CPI / Core CPI",                     "Inflation", "High")
US - Cleveland Fed CPI                      -> ("Cleveland Fed CPI / Median CPI",     "Inflation", "High")
US - Median CPI (Mar)                       -> ("Cleveland Fed CPI / Median CPI",     "Inflation", "High")
US - U Mich Sentiment / Inflation Expects   -> ("U Mich Inflation Expectations",      "Inflation", "High")
University of Michigan Inflation Expects    -> ("U Mich Inflation Expectations",      "Inflation", "High")
Australia - Trimmed Mean CPI                -> ("Trimmed Mean CPI",                   "Inflation", "High")
US - PCE / Core PCE                         -> ("PCE / Core PCE",                     "Inflation", "High")
US - PPI Final Demand                       -> ("PPI",                                "Inflation", "High")
Eurozone - HICP Final YY                    -> ("HICP",                               "Inflation", "High")
Some bespoke survey                         -> ("Some bespoke survey",                "",          "Low")
```

### `tests/test_dedup.py` (10 checks)

Exercises `release_key` and `dedup_releases` end-to-end. Key cases:

```python
r_a   = "United States - Retail Sales MM (Mar)",       date "2026-04-21", imp "****"
r_b   = "United States - Retail Sales / Ex-Autos (Mar)", date "2026-04-21", imp "****"
r_prev= "United States - Retail Sales MM (Feb)",       date "2026-03-17", imp "****"

assert release_key(r_a) == release_key(r_b)          # same event, two parses
assert release_key(r_a) != release_key(r_prev)       # different period, distinct
assert dedup_releases([r_a, r_b, r_prev]) == [r_a, r_prev]
```

Note that the test passes only because `r_a` and `r_b` happen to share the
same `(country, normalized_name, date, importance)`. It's silent about what
happens when importance flips between frozen and live for the same event.

### `tests/test_country.py` (19 checks) and `tests/test_catalogue.py` (4 checks)

Mostly verify that `normalize_release_name` doesn't misclassify across
countries (UK HMRC Payrolls ≠ NFP) and that the catalogue groups CPI /
Labour Force correctly.

---

## Full source

```python
"""Release-name normalization.

Maps a free-form release title to a canonical recurring release name plus a
theme and a confidence flag. The normalizer is intentionally conservative:
when in doubt we keep the original cleaned title rather than collapsing
unrelated releases together.

Stable key contract:
    catalogue uses (country, normalized_name) as the grouping key.
    Institutional/source variants are kept as DISTINCT normalized names,
    so e.g. "Cleveland Fed CPI / Median CPI" and "CPI / Core CPI" never
    collapse together even though both contain "CPI".

Confidence:
    High   - title clearly maps to a known recurring release pattern.
    Medium - keyword-based / generic ("Business Survey", "Consumer Confidence").
    Low    - vague title; fall back to the original cleaned title and DO NOT
             group with anything else.
"""
from __future__ import annotations

import re
from typing import Tuple

from utils.text import release_type

# Order matters - more specific rules MUST come before generic ones.
# Each rule: (compiled_pattern, canonical_name, theme, confidence)
_RULES = [
    # ============================================================
    # Inflation - INSTITUTIONAL / SOURCE-SPECIFIC variants first.
    # These must be checked BEFORE the generic CPI rule so they
    # are never collapsed into "CPI / Core CPI".
    # ============================================================
    (re.compile(r"\bcleveland\s+fed\b.*\bcpi\b|\bcleveland\s+fed\s+(?:median|trimmed)|\bmedian\s+cpi\b", re.I),
                                                                    "Cleveland Fed CPI / Median CPI", "Inflation", "High"),
    (re.compile(r"\b(?:u[\s\.]*mich(?:igan)?|university\s+of\s+michigan)\b.{0,40}\binflation\s+expectations?\b", re.I),
                                                                    "U Mich Inflation Expectations", "Inflation", "High"),
    (re.compile(r"\b(?:u[\s\.]*mich(?:igan)?|university\s+of\s+michigan)\b.{0,40}\b(?:sentiment|consumer)\b", re.I),
                                                                    "U Mich Sentiment", "Growth", "High"),
    (re.compile(r"\b(?:ny\s+fed|new\s+york\s+fed)\b.{0,30}\binflation\s+expectations?\b", re.I),
                                                                    "NY Fed Inflation Expectations", "Inflation", "High"),
    (re.compile(r"\binflation\s+expectations?\b", re.I),            "Inflation Expectations", "Inflation", "Medium"),
    (re.compile(r"\b(?:trimmed[\s-]?mean|weighted[\s-]?median)\s+cpi\b", re.I),
                                                                    "Trimmed Mean CPI", "Inflation", "High"),
    (re.compile(r"\bhicp\b", re.I),                                 "HICP", "Inflation", "High"),
    (re.compile(r"\bppi\b|\bproducer\s+price", re.I),               "PPI", "Inflation", "High"),
    (re.compile(r"\bpce\b|\bpersonal\s+consumption\s+expenditure", re.I),
                                                                    "PCE / Core PCE", "Inflation", "High"),
    (re.compile(r"\bimport\s+prices?\b", re.I),                     "Import Prices", "Inflation", "Medium"),
    # Generic CPI rule - LAST among inflation rules
    (re.compile(r"\b(?:headline|core)?\s*cpi(?:\s+indicator)?\b", re.I),
                                                                    "CPI / Core CPI", "Inflation", "High"),

    # ============================================================
    # Labour
    # ============================================================
    # NFP only - generic "payrolls?" was catching unrelated UK labour-market
    # headers like "HMRC Payrolls Change". The release must explicitly say
    # "non-farm payrolls" or "NFP" to qualify.
    (re.compile(r"\b(?:non[\s-]?farm\s+payrolls?|nfp)\b", re.I),
                                                                    "Non-Farm Payrolls", "Labor", "High"),
    (re.compile(r"\b(?:labou?r\s+force|employment\s+change|unemployment\s+rate|jobs?\s+report)\b", re.I),
                                                                    "Labour Force", "Labor", "High"),
    (re.compile(r"\bjobless\s+claims\b|\binitial\s+claims\b", re.I), "Jobless Claims", "Labor", "High"),
    (re.compile(r"\bwage\s+price\s+index\b", re.I),                  "Wage Price Index", "Labor", "High"),
    (re.compile(r"\b(?:average\s+earnings|hourly\s+earnings|wage\s+growth)\b", re.I),
                                                                    "Average Earnings", "Labor", "High"),
    (re.compile(r"\bjolts?\b|\bjob\s+openings\b", re.I),             "JOLTS", "Labor", "High"),
    (re.compile(r"\badp\b\s+(?:employment|payroll)", re.I),          "ADP Employment", "Labor", "High"),

    # ============================================================
    # Policy
    # ============================================================
    (re.compile(r"\b(?:rba|fomc|fed|ecb|boe|boj|boc|snb|riksbank|norges|pboc|cbrt|sarb|banxico|bcb|nbp|rbi|rbnz)\s+minutes\b", re.I),
                                                                    "Central Bank Minutes", "Policy", "High"),
    (re.compile(r"\b(?:rate\s+decision|policy\s+rate|interest\s+rate\s+decision|cash\s+rate|monetary\s+policy|repo\s+rate|refinancing\s+rate)\b", re.I),
                                                                    "Central Bank Decision", "Policy", "High"),
    (re.compile(r"\b(?:fomc|ecb|boe|boj|rba|boc|snb|riksbank|norges|pboc|sarb|banxico|cbrt|rbi|rbnz)\s+(?:decision|meeting|statement)\b", re.I),
                                                                    "Central Bank Decision", "Policy", "High"),

    # ============================================================
    # Growth
    # ============================================================
    (re.compile(r"\b(?:gdp|gross\s+domestic\s+product)\b", re.I),    "GDP", "Growth", "High"),
    (re.compile(r"\bretail\s+sales\b", re.I),                        "Retail Sales", "Growth", "High"),
    (re.compile(r"\bpmi\b|\bpurchasing\s+managers\b", re.I),         "PMI", "Growth", "High"),
    (re.compile(r"\bism\b", re.I),                                   "ISM", "Growth", "High"),
    (re.compile(r"\bifo\b", re.I),                                   "Ifo Business Climate", "Growth", "High"),
    (re.compile(r"\bzew\b", re.I),                                   "ZEW Sentiment", "Growth", "High"),
    (re.compile(r"\bindustrial\s+production\b|manuf[a-z]*\s+production", re.I),
                                                                    "Industrial Production", "Growth", "High"),
    (re.compile(r"\b(?:durable|capital)\s+goods\b", re.I),           "Durable Goods", "Growth", "Medium"),
    (re.compile(r"\b(?:nfib|small\s+business)\b", re.I),             "NFIB Small Business", "Growth", "Medium"),
    (re.compile(r"\b(?:business\s+survey|business\s+confidence|business\s+climate|nab\s+business)\b", re.I),
                                                                    "Business Survey", "Growth", "Medium"),
    (re.compile(r"\b(?:consumer\s+confidence|consumer\s+sentiment|westpac\s+consumer)\b", re.I),
                                                                    "Consumer Confidence", "Growth", "Medium"),
    (re.compile(r"\btankan\b", re.I),                                "Tankan", "Growth", "High"),
    (re.compile(r"\b(?:factory\s+orders|machine\s+orders)\b", re.I), "Factory Orders", "Growth", "Medium"),

    # ============================================================
    # External
    # ============================================================
    (re.compile(r"\btrade\s+balance\b|\bmerchandise\s+trade\b", re.I), "Trade Balance", "External", "High"),
    (re.compile(r"\bcurrent\s+account\b", re.I),                       "Current Account", "External", "High"),
    (re.compile(r"\b(?:exports?|imports?)\s+(?:yy|mm|y/y|m/m)\b", re.I), "Trade Balance", "External", "Medium"),
    (re.compile(r"\b(?:fx|foreign\s+exchange)\s+reserves?\b", re.I),   "FX Reserves", "External", "Medium"),

    # ============================================================
    # Housing
    # ============================================================
    (re.compile(r"\bbuilding\s+approvals?\b|\bbuilding\s+permits?\b", re.I),
                                                                    "Building Approvals", "Housing", "High"),
    (re.compile(r"\bhousing\s+starts?\b", re.I),                    "Housing Starts", "Housing", "High"),
    (re.compile(r"\bhouse\s+price|home\s+price", re.I),             "House Prices", "Housing", "Medium"),
    (re.compile(r"\bexisting\s+home\s+sales?\b|\bnew\s+home\s+sales?\b", re.I),
                                                                    "Home Sales", "Housing", "Medium"),
    (re.compile(r"\bmortgage\s+(?:applications|rate)\b", re.I),     "Mortgage Activity", "Housing", "Medium"),
]


def normalize_release_name(title) -> Tuple[str, str, str]:
    """Return (canonical_name, theme, confidence).

    Confidence:
      High   - matched a known institutional/recurring pattern.
      Medium - keyword-based generic match.
      Low    - no rule matched; fall back to the cleaned original title and
               DO NOT group with anything else.
    """
    if not title:
        return "", "", "Low"
    cleaned = release_type(title) or title.strip()
    # Search both the cleaned title and the raw title so multi-token indicators
    # still match if release_type was overly aggressive.
    haystack = cleaned + " " + title
    for pat, name, theme, conf in _RULES:
        if pat.search(haystack):
            return name, theme, conf
    # Low confidence fallback - keep the cleaned original title to avoid
    # collapsing this release with anything else in the catalogue.
    return cleaned, "", "Low"


def is_known(title) -> bool:
    """True if normalize_release_name returns a High/Medium-confidence match."""
    _, _, conf = normalize_release_name(title)
    return conf in {"High", "Medium"}


def release_key(release) -> str:
    """Stable dedup key: country | normalized_name | date | importance.

    Two release blocks parsed from different parts of the same archive
    that describe the same Reuters event will produce the same key, even
    if the surrounding commentary differs.
    """
    if release is None:
        return ""
    country = ""
    if getattr(release, "countries", None):
        country = release.countries[0] or ""
    name, _theme, _conf = normalize_release_name(getattr(release, "title", "") or "")
    date = getattr(release, "date_str", "") or ""
    importance = getattr(release, "importance", "") or ""
    return f"{country}|{name}|{date}|{importance}"


def dedup_releases(releases):
    """Drop duplicates on release_key, keeping the FIRST occurrence."""
    seen = set()
    out = []
    for r in releases or []:
        k = release_key(r)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out
```

---

## What we'd specifically like ChatGPT to look for

1. **Reference-period extraction.** Sketch what
   `extract_reference_period(title, raw_block, date_str)` should return for
   the cases that appear in the archive:
   `US - CPI (Mar)`, `Eurozone - HICP Final YY`, `Australia - GDP Q1`,
   `US - PCE / Core PCE`. Should it return a `(year, month)` tuple, a string,
   a date? How does it survive titles without an explicit period (e.g.
   `Jobless Claims`)? Where does it pull data from when the title doesn't
   carry the period — first line of `raw_block`?

2. **Rewrite of `release_key` for catalogue use.** Propose the exact
   signature, what fields go in, and what the behaviour is when
   `reference_period` can't be extracted (drop into per-release-date
   fallback? Group all unparseable into one bucket?).

3. **Audit `_RULES` for false positives / false negatives.** Pay special
   attention to the policy section (the long alternation of central-bank
   acronyms is brittle — does `\bfed\s+minutes\b` accidentally match
   `Federal Reserve minutes`? Does the generic CPI rule match a sentence
   like `the CPI indicator missed`?). Suggest concrete patches with example
   titles.

4. **`is_known` is unused.** Confirm whether anything calls it (we
   couldn't find a caller). If not, decide whether to keep it as a
   stable public helper or drop it.

5. **Empty-title and None safety.** `normalize_release_name(None)` works,
   but `normalize_release_name(123)` would crash. Worth defending against,
   or YAGNI?

6. **Rule-table maintainability.** Is the giant `_RULES` list still the
   right shape, or should it be split into per-theme dicts (Inflation,
   Labor, Policy, …) loaded from a YAML/JSON the user can edit without
   touching code?

Don't propose new files yet — give us the textual recommendations and we
will translate to code.
