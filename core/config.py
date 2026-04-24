"""
Central configuration for the Macro FX Feed Dashboard.

All GitHub coordinates, file conventions, scope definitions, and marker
stems live here. Derived from a live probe of
jeangaga/mon-mini-chat-bot/main/notes/ (Apr 2026).
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# GitHub source
# ---------------------------------------------------------------------------

GITHUB_OWNER = os.getenv("MACRO_REPO_OWNER", "jeangaga")
GITHUB_REPO = os.getenv("MACRO_REPO_NAME", "mon-mini-chat-bot")
GITHUB_BRANCH = os.getenv("MACRO_REPO_BRANCH", "main")
GITHUB_NOTES_DIR = os.getenv("MACRO_REPO_NOTES_DIR", "notes")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip() or None

# ---------------------------------------------------------------------------
# Local cache
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SECONDS = int(os.getenv("MACRO_CACHE_TTL", "300"))

# ---------------------------------------------------------------------------
# Scope taxonomy
# ---------------------------------------------------------------------------

REGION_SCOPES = ["USD", "EUR", "DM", "EM"]
CURRENCY_SCOPES_DM = ["AUD", "CAD", "CHF", "GBP", "JPY", "NOK", "SEK"]
CURRENCY_SCOPES_EM = ["BRL", "CNH", "INR", "KRW", "MXN", "PLN", "TRY", "TWD", "ZAR"]
PM_SCOPES = ["WEEKPM", "MACROPM", "SHORT_WEEK", "ARC"]

ALL_SCOPES = REGION_SCOPES + CURRENCY_SCOPES_DM + CURRENCY_SCOPES_EM + PM_SCOPES

SCOPE_GROUP = {
    **{s: "Region" for s in REGION_SCOPES},
    **{s: "DM currency" for s in CURRENCY_SCOPES_DM},
    **{s: "EM currency" for s in CURRENCY_SCOPES_EM},
    **{s: "PM / shared" for s in PM_SCOPES},
}

REGIONS = REGION_SCOPES

# ---------------------------------------------------------------------------
# Scope -> files map
# ---------------------------------------------------------------------------

SCOPE_FILES = {
    "USD": {"frozen_week": "USD_WEEK.txt", "live_week": "USD_WEEK_LIVE_MACRO.txt",
            "pm_style": "WEEKPM.txt", "macro_note": "USD_MACRO_NOTE.txt"},
    "EUR": {"frozen_week": "EUR_WEEK.txt", "live_week": "EUR_WEEK_LIVE_MACRO.txt",
            "pm_style": "WEEKPM.txt", "macro_note": "EUR_MACRO_NOTE.txt"},
    "DM":  {"frozen_week": "DM_WEEK.txt",  "live_week": "DM_WEEK_LIVE_MACRO.txt",
            "pm_style": "WEEKPM.txt", "macro_note": ""},
    "EM":  {"frozen_week": "EM_WEEK.txt",  "live_week": "EM_WEEK_LIVE_MACRO.txt",
            "pm_style": "WEEKPM.txt", "macro_note": ""},
    "AUD": {"frozen_week": "AUD_WEEK.txt", "live_week": "", "pm_style": "",
            "macro_note": "AUD_MACRO_NOTE.txt"},
    "CAD": {"frozen_week": "CAD_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "CHF": {"frozen_week": "CHF_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "GBP": {"frozen_week": "GBP_WEEK.txt", "live_week": "", "pm_style": "",
            "macro_note": "GBP_MACRO_NOTE.txt"},
    "JPY": {"frozen_week": "JPY_WEEK.txt", "live_week": "", "pm_style": "",
            "macro_note": "JPY_MACRO_NOTE.txt"},
    "NOK": {"frozen_week": "NOK_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "SEK": {"frozen_week": "SEK_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "BRL": {"frozen_week": "BRL_WEEK.txt", "live_week": "", "pm_style": "",
            "macro_note": "BRL_MACRO_NOTE.txt"},
    "CNH": {"frozen_week": "CNH_WEEK.txt", "live_week": "", "pm_style": "",
            "macro_note": "CNH_MACRO_NOTE.txt"},
    "INR": {"frozen_week": "INR_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "KRW": {"frozen_week": "KRW_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "MXN": {"frozen_week": "MXN_WEEK.txt", "live_week": "", "pm_style": "",
            "macro_note": "MXN_MACRO_NOTE.txt"},
    "PLN": {"frozen_week": "PLN_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "TRY": {"frozen_week": "TRY_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "TWD": {"frozen_week": "TWD_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "ZAR": {"frozen_week": "ZAR_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "WEEKPM":     {"frozen_week": "", "live_week": "", "pm_style": "WEEKPM.txt",     "macro_note": ""},
    "MACROPM":    {"frozen_week": "", "live_week": "", "pm_style": "MACROPM.txt",    "macro_note": ""},
    "SHORT_WEEK": {"frozen_week": "SHORT_WEEK.txt", "live_week": "", "pm_style": "", "macro_note": ""},
    "ARC":        {"frozen_week": "ARC.txt",        "live_week": "", "pm_style": "", "macro_note": ""},
}

REGION_FILES = SCOPE_FILES

ALL_NOTE_FILES = sorted({
    f for scope_map in SCOPE_FILES.values() for f in scope_map.values() if f
})

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

MARKER_PREFIX = "<<"
MARKER_SUFFIX = ">>"

BLOCK_STEMS = {
    "frozen_week": [
        "AUD_WEEK", "BRL_WEEK", "CAD_WEEK", "CHF_WEEK", "CNH_WEEK",
        "DM_WEEK", "EM_WEEK", "EUR_WEEK", "GBP_WEEK", "INR_WEEK",
        "JPY_WEEK", "KRW_WEEK", "MXN_WEEK", "NOK_WEEK", "PLN_WEEK",
        "SEK_WEEK", "SHORT_WEEK", "TRY_WEEK", "TWD_WEEK", "USD_WEEK",
        "ZAR_WEEK",
    ],
    "live_week": [
        "DM_WEEK_LIVE_MACRO", "EM_WEEK_LIVE_MACRO",
        "EUR_WEEK_LIVE_MACRO", "USD_WEEK_LIVE_MACRO",
    ],
    "pm_style": [
        "ARC", "MACROPM", "WEEKPM",
        "USD_WEEK_PM_STYLE", "EUR_WEEK_PM_STYLE",
        "DM_WEEK_PM_STYLE", "EM_WEEK_PM_STYLE",
    ],
    "macro_note": [
        "AUD_MACRO_NOTE", "BRL_MACRO_NOTE", "CNH_MACRO_NOTE",
        "EUR_MACRO_NOTE", "GBP_MACRO_NOTE", "JPY_MACRO_NOTE",
        "MXN_MACRO_NOTE", "USD_MACRO_NOTE", "US_MACRO_NOTE",
    ],
}

# ---------------------------------------------------------------------------
# Importance flags
# ---------------------------------------------------------------------------

IMPORTANCE_LEVELS = ["*", "**", "***", "****"]
IMPORTANCE_LABELS = {"*": "Low", "**": "Medium", "***": "High", "****": "Top"}

# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

THEME_KEYWORDS = {
    "Inflation": [
        "CPI", "HICP", "PPI", "WPI", "PCE",
        "import prices", "export prices", "inflation expectations",
        "wages", "unit labor cost", "ULC", "core inflation",
        "headline inflation", "price index", "deflator",
    ],
    "Labor": [
        "payroll", "NFP", "unemployment", "jobless", "labor force",
        "labour force", "employment", "jobs report", "JOLTS",
        "initial claims", "continuing claims", "wage growth", "earnings",
    ],
    "Growth": [
        "GDP", "retail sales", "industrial production", "manufacturing",
        "PMI", "ISM", "durable goods", "factory orders", "services PMI",
        "composite PMI", "consumer spending", "capex", "investment",
    ],
    "Policy": [
        "FOMC", "ECB", "BoE", "BoJ", "RBA", "RBNZ", "BoC", "SNB", "Riksbank",
        "Norges", "PBoC", "LPR", "minutes", "rate decision", "policy",
        "hawkish", "dovish", "hike", "cut",
    ],
    "FX": [
        "FX", "foreign exchange", "reserves", "intervention",
        "trade balance", "current account", "TIC flows",
    ],
    "Housing": [
        "housing starts", "building permits", "home sales",
        "Case-Shiller", "mortgage", "NAHB", "construction",
    ],
}

ALL_THEMES = list(THEME_KEYWORDS.keys())

# ---------------------------------------------------------------------------
# Country detection
# ---------------------------------------------------------------------------

COUNTRY_ALIASES = {
    "US":          ["US ", "U.S.", "United States", "American"],
    "Germany":     ["Germany", "German", " DE ", "Bund"],
    "France":      ["France", "French"],
    "Italy":       ["Italy", "Italian"],
    "Spain":       ["Spain", "Spanish"],
    "UK":          ["UK ", "United Kingdom", "British", "Britain"],
    "Japan":       ["Japan", "Japanese", "BoJ"],
    "Canada":      ["Canada", "Canadian", "BoC"],
    "Australia":   ["Australia", "Australian", "RBA", "AUD"],
    "New Zealand": ["New Zealand", "RBNZ", "NZD"],
    "China":       ["China", "Chinese", "PBoC", "CNH", "CNY"],
    "Korea":       ["Korea", "Korean", "KRW"],
    "India":       ["India", "Indian", "INR", "RBI"],
    "Brazil":      ["Brazil", "Brazilian", "BRL", "BCB"],
    "Mexico":      ["Mexico", "Mexican", "MXN", "Banxico"],
    "Turkey":      ["Turkey", "Turkish", "TRY", "CBRT"],
    "Poland":      ["Poland", "Polish", "PLN", "NBP"],
    "Switzerland": ["Switzerland", "Swiss", "SNB", "CHF"],
    "Norway":      ["Norway", "Norwegian", "Norges", "NOK"],
    "Sweden":      ["Sweden", "Swedish", "Riksbank", "SEK"],
    "Eurozone":    ["Eurozone", "Euro area", "Euro Area", "EA "],
    "Taiwan":      ["Taiwan", "TWD"],
    "South Africa": ["South Africa", "ZAR", "SARB"],
}

SCOPE_COUNTRIES = {
    "USD": ["US"],
    "EUR": ["Germany", "France", "Italy", "Spain", "Eurozone"],
    "DM":  ["UK", "Japan", "Canada", "Australia", "New Zealand",
            "Switzerland", "Norway", "Sweden"],
    "EM":  ["China", "Korea", "India", "Brazil", "Mexico", "Turkey",
            "Poland", "Taiwan", "South Africa"],
    "AUD": ["Australia"], "CAD": ["Canada"], "CHF": ["Switzerland"],
    "GBP": ["UK"], "JPY": ["Japan"], "NOK": ["Norway"], "SEK": ["Sweden"],
    "BRL": ["Brazil"], "CNH": ["China"], "INR": ["India"], "KRW": ["Korea"],
    "MXN": ["Mexico"], "PLN": ["Poland"], "TRY": ["Turkey"],
    "TWD": ["Taiwan"], "ZAR": ["South Africa"],
}

REGION_COUNTRIES = SCOPE_COUNTRIES
