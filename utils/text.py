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
            # (?<!\w) and (?!\w) are stronger than \b for aliases that begin
            # or end with a non-word character such as "U.S.".
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
    line of the title. Word-boundary matching prevents false positives like
    "US " matching inside "Bonus".
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


# ---------------------------------------------------------------------------
# Reference-period extraction
# ---------------------------------------------------------------------------
# Catalogue grouping needs to know WHICH period a release describes (e.g. CPI
# "for March"), independent of the release/publication date. The signal lives
# in the trailing parenthesized token of the title.
#
#   "United States - Retail Sales MM (Mar)"  -> "2026-03"
#   "Australia - GDP (Q1)"                   -> "2026-Q1"
#   "Eurozone - HICP Final YY"               -> None (no period token)
#
# Year is inferred from `release_date`. Year-rollover heuristic: if the
# parenthesized month is greater than `release_date.month`, the print is
# describing the prior calendar year (e.g. "(Dec)" published in Jan).

_REF_MONTH_TOKENS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_REF_PARENS_RE = re.compile(r"\(([^)]+)\)")
_REF_QUARTER_RE = re.compile(r"^\s*Q\s*([1-4])\s*$", re.I)


def extract_reference_period(title, release_date=None):
    """Return the reference period implied by a release title.

    Returns:
        "YYYY-MM" for a (Mon) token,
        "YYYY-QX" for a (Q1)..(Q4) token,
        None if no recognizable period token is present.

    Year is inferred from `release_date.year`. When the parenthesized month
    is greater than release_date.month we subtract a year (e.g. "(Dec)"
    published in Jan -> previous year).
    """
    if not title:
        return None
    year = release_date.year if release_date is not None else None
    for m in _REF_PARENS_RE.finditer(title):
        token = m.group(1).strip()
        if not token:
            continue
        # Quarter: "Q1", "Q 1", "q4"
        qm = _REF_QUARTER_RE.match(token)
        if qm:
            if year is None:
                return None
            return f"{year}-Q{qm.group(1)}"
        # Month: take the FIRST month-like word in the token. This handles
        # "Mar", "March", "Mar P", "Mar F" (preliminary/final markers), and
        # "Mar/Feb" (revision: latest period wins via first word).
        first_word = re.split(r"[\s/,;]+", token, 1)[0].lower()
        first_word = first_word.rstrip(".")
        mi = _REF_MONTH_TOKENS.get(first_word) or _REF_MONTH_TOKENS.get(first_word[:3])
        if mi is None:
            continue
        if year is None:
            return None
        ref_year = year
        if release_date is not None and mi > release_date.month:
            ref_year = year - 1
        return f"{ref_year}-{mi:02d}"
    return None
