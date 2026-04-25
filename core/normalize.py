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
    (re.compile(r"\b(?:non[\s-]?farm\s+payroll|nfp|payrolls?)\b", re.I),
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
