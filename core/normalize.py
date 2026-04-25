"""Release-name normalization.

Maps a free-form release title (already stripped of country prefix and trailing
date by `release_type()`) to a canonical, recurring release name plus a theme
and a confidence flag. Confidence is High when the title clearly matches a
well-known indicator family, Medium for fuzzier matches, and Low when we fall
back to the original cleaned title.

The normalizer is intentionally conservative: when in doubt we keep the
original title rather than collapsing unrelated releases together.
"""
from __future__ import annotations

import re
from typing import Tuple

from utils.text import release_type

# (compiled_pattern, canonical_name, theme, confidence)
# Order matters: more specific patterns first.
_RULES = [
    # --- Inflation -------------------------------------------------------
    (re.compile(r"\bhicp\b", re.I),                                "HICP", "Inflation", "High"),
    (re.compile(r"\bcpi(?:\s+indicator)?\b|trimmed[\s-]?mean", re.I), "CPI", "Inflation", "High"),
    (re.compile(r"\bppi\b|producer\s+price", re.I),                "PPI", "Inflation", "High"),
    (re.compile(r"\bpce\b|personal\s+consumption\s+expenditure", re.I), "PCE", "Inflation", "High"),
    (re.compile(r"\binflation\s+expectation", re.I),               "Inflation Expectations", "Inflation", "Medium"),
    (re.compile(r"\bimport\s+prices?\b", re.I),                    "Import Prices", "Inflation", "Medium"),

    # --- Labour ----------------------------------------------------------
    (re.compile(r"\b(?:non[\s-]?farm\s+payroll|nfp|payrolls?)\b", re.I), "Non-Farm Payrolls", "Labor", "High"),
    (re.compile(r"\b(?:labou?r\s+force|employment\s+change|unemployment\s+rate|jobs?\s+report)\b", re.I),
                                                                    "Labour Force", "Labor", "High"),
    (re.compile(r"\bjobless\s+claims\b|initial\s+claims", re.I),    "Jobless Claims", "Labor", "High"),
    (re.compile(r"\bwage\s+price\s+index\b", re.I),                 "Wage Price Index", "Labor", "High"),
    (re.compile(r"\b(?:average\s+earnings|hourly\s+earnings|wage\s+growth)\b", re.I),
                                                                    "Average Earnings", "Labor", "High"),
    (re.compile(r"\bjolts?\b|job\s+openings", re.I),                "JOLTS", "Labor", "High"),
    (re.compile(r"\badp\b\s+(?:employment|payroll)", re.I),         "ADP Employment", "Labor", "High"),

    # --- Policy ----------------------------------------------------------
    (re.compile(r"\b(?:rba|fomc|fed|ecb|boe|boj|boc|snb|riksbank|norges|pboc|cbrt|sarb|banxico|bcb|nbp|rbi|rbnz)\s+minutes\b", re.I),
                                                                    "Central Bank Minutes", "Policy", "High"),
    (re.compile(r"\b(?:rate\s+decision|policy\s+rate|interest\s+rate\s+decision|cash\s+rate|monetary\s+policy|repo\s+rate|refinancing\s+rate)\b", re.I),
                                                                    "Central Bank Decision", "Policy", "High"),
    (re.compile(r"\b(?:fomc|ecb|boe|boj|rba|boc|snb|riksbank|norges|pboc|sarb|banxico|cbrt)\s+(?:decision|meeting|statement)\b", re.I),
                                                                    "Central Bank Decision", "Policy", "High"),

    # --- Growth ----------------------------------------------------------
    (re.compile(r"\b(?:gdp|gross\s+domestic\s+product)\b", re.I),   "GDP", "Growth", "High"),
    (re.compile(r"\bretail\s+sales\b", re.I),                       "Retail Sales", "Growth", "High"),
    (re.compile(r"\bpmi\b|purchasing\s+managers", re.I),            "PMI", "Growth", "High"),
    (re.compile(r"\bism\b", re.I),                                  "ISM", "Growth", "High"),
    (re.compile(r"\bifo\b", re.I),                                  "Ifo Business Climate", "Growth", "High"),
    (re.compile(r"\bzew\b", re.I),                                  "ZEW Sentiment", "Growth", "High"),
    (re.compile(r"\bindustrial\s+production\b|manuf[a-z]*\s+production", re.I),
                                                                    "Industrial Production", "Growth", "High"),
    (re.compile(r"\b(?:durable|capital)\s+goods\b", re.I),          "Durable Goods", "Growth", "Medium"),
    (re.compile(r"\b(?:nfib|small\s+business)\b", re.I),            "NFIB Small Business", "Growth", "Medium"),
    (re.compile(r"\b(?:business\s+survey|business\s+confidence|business\s+climate|nab\s+business)\b", re.I),
                                                                    "Business Survey", "Growth", "Medium"),
    (re.compile(r"\b(?:consumer\s+confidence|consumer\s+sentiment|westpac\s+consumer)\b", re.I),
                                                                    "Consumer Confidence", "Growth", "Medium"),
    (re.compile(r"\b(?:tankan)\b", re.I),                           "Tankan", "Growth", "High"),
    (re.compile(r"\b(?:factory\s+orders|machine\s+orders)\b", re.I),"Factory Orders", "Growth", "Medium"),

    # --- External --------------------------------------------------------
    (re.compile(r"\btrade\s+balance\b|merchandise\s+trade", re.I),  "Trade Balance", "External", "High"),
    (re.compile(r"\bcurrent\s+account\b", re.I),                    "Current Account", "External", "High"),
    (re.compile(r"\b(?:exports?|imports?)\s+(?:yy|mm|y/y|m/m)\b", re.I), "Trade Balance", "External", "Medium"),
    (re.compile(r"\b(?:fx|foreign\s+exchange)\s+reserves?\b", re.I),"FX Reserves", "External", "Medium"),

    # --- Housing ---------------------------------------------------------
    (re.compile(r"\bbuilding\s+approvals?\b|building\s+permits?\b", re.I),
                                                                    "Building Approvals", "Housing", "High"),
    (re.compile(r"\bhousing\s+starts?\b", re.I),                    "Housing Starts", "Housing", "High"),
    (re.compile(r"\bhouse\s+price|home\s+price", re.I),             "House Prices", "Housing", "Medium"),
    (re.compile(r"\bexisting\s+home\s+sales?\b|new\s+home\s+sales?\b", re.I),
                                                                    "Home Sales", "Housing", "Medium"),
    (re.compile(r"\bmortgage\s+(?:applications|rate)\b", re.I),     "Mortgage Activity", "Housing", "Medium"),
]


def normalize_release_name(title) -> Tuple[str, str, str]:
    """Return (canonical_name, theme, confidence).

    Confidence is one of "High", "Medium", "Low" - "Low" means we did not
    match a known family and fell back to the original cleaned title.
    """
    if not title:
        return "", "", "Low"
    cleaned = release_type(title) or title.strip()
    # Some titles are like "Australia - CPI - 23 Apr 2026"; release_type already
    # peels off the country prefix and trailing date for us. We still scan the
    # raw title so multi-token indicators still match if release_type was overly
    # aggressive.
    haystack = cleaned + " " + (title or "")
    for pat, name, theme, conf in _RULES:
        if pat.search(haystack):
            return name, theme, conf
    # Fallback: keep the cleaned original title as the "name", no theme,
    # confidence Low.
    return cleaned, "", "Low"


def is_known(title) -> bool:
    """True if normalize_release_name returns a High/Medium-confidence match."""
    _, _, conf = normalize_release_name(title)
    return conf in {"High", "Medium"}
