"""Text helpers: importance-flag detection, country/theme tagging, date detection."""
from __future__ import annotations

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


def detect_countries(text):
    if not text:
        return []
    matches = []
    lower = text.lower()
    for country, aliases in COUNTRY_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lower:
                matches.append(country)
                break
    return matches


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


def collapse_blank_lines(text):
    if not text:
        return text
    return re.sub(r"\n{3,}", "\n\n", text)


def any_keyword(text, keywords):
    if not text:
        return False
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)
