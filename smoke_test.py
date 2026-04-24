"""
Offline smoke test for the parser + search layers.

Builds a synthetic file that mimics the marker conventions in the real
archive and asserts that:

  * extract_blocks finds the marker-delimited sections
  * extract_releases pulls out the importance-flagged paragraphs
  * filter_releases honours importance / region / theme filters
  * parse_command maps QUICK-style shortcuts to filter kwargs

Run:
    python smoke_test.py
"""
from __future__ import annotations

import sys

from core.loaders import LoadResult
from core.parsers import (
    extract_blocks,
    extract_releases,
    releases_from_load_results,
)
from core.search import filter_releases, inflation_releases, parse_command


SAMPLE_DM = """<<DM_WEEK_BEGIN>>
DM WEEK — w/c 20 Apr 2026

Signal scoreboard
Growth: ~
Labor: +
Inflation: ~
Policy constraint: +

Australia — Labour Force — 17 Apr 2026 | ****
Actual: +32k vs poll +20k, prior +15k (rev).
Unemployment rate 3.9% vs 4.0% poll.
Economist layer: tight labor market persisting, wages sticky.
HF take: marginal RBA hawkish; AUD supported into CPI.

Australia — CPI — 23 Apr 2026 | ****
Q1 headline 0.9% q/q vs 0.8% poll.
Trimmed mean 0.8% vs 0.7% poll.
HF take: upside surprise supports no-cut narrative.

RBA Minutes — 18 Apr 2026 | ***
Debate around when sufficient progress on inflation is seen.
HF take: balanced but watchful, no urgency to cut.

Canada — CPI — 16 Apr 2026 | ***
Headline 2.6% y/y vs 2.5% poll.

Japan — Trade Balance — 17 Apr 2026 | **
Marginal surplus; exports soft.
<<DM_WEEK_END>>
"""

SAMPLE_EUR = """<<EUR_WEEK_BEGIN>>
EUR WEEK — w/c 20 Apr 2026

Germany — HICP — 22 Apr 2026 | ****
Headline 2.3% y/y vs 2.2% poll; services stuck around 3.4%.
HF take: ECB pushback on June cut bets plausible.

ECB Account — 17 Apr 2026 | ***
Mentions of "restrictiveness already sufficient" but balance mixed.

France — PPI — 21 Apr 2026 | **
Soft; in line.
<<EUR_WEEK_END>>
"""


def _make_loadresult(filename: str, text: str) -> LoadResult:
    return LoadResult(filename=filename, text=text, source="github", fetched_at=0.0)


def main() -> int:
    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)
        else:
            print(f"  ok — {msg}")

    print("[1] extract_blocks")
    blocks_dm = extract_blocks(SAMPLE_DM, source_file="DM_WEEK.txt")
    check(len(blocks_dm) == 1, "one DM_WEEK block found")
    check(blocks_dm[0].stem == "DM_WEEK", "stem is DM_WEEK")
    check(blocks_dm[0].region == "DM", "region derives to DM")

    print("[2] extract_releases (DM)")
    dm_releases = extract_releases(blocks_dm[0])
    titles = [r.title for r in dm_releases]
    check(len(dm_releases) >= 5, f"≥5 releases found (got {len(dm_releases)}): {titles}")
    top = [r for r in dm_releases if r.importance == "****"]
    check(len(top) == 2, f"two **** releases in DM (got {len(top)})")

    print("[3] country/theme detection")
    cpi_hits = [r for r in dm_releases if "CPI" in r.title]
    check(any("Australia" in r.countries for r in cpi_hits), "Australia CPI tagged with Australia")
    check(any("Inflation" in r.themes for r in cpi_hits), "Australia CPI tagged with Inflation theme")

    print("[4] filter by importance")
    filtered = filter_releases(dm_releases, min_importance="****")
    check(len(filtered) == 2, "only **** releases pass ****-min filter")

    print("[5] filter by theme")
    inflation = filter_releases(dm_releases, themes=["Inflation"])
    check(len(inflation) >= 2, f"≥2 inflation-tagged releases in DM (got {len(inflation)})")

    print("[6] inflation_releases helper")
    eur_blocks = extract_blocks(SAMPLE_EUR, source_file="EUR_WEEK.txt")
    eur_releases = extract_releases(eur_blocks[0])
    all_releases = dm_releases + eur_releases
    infl = inflation_releases(all_releases)
    check(len(infl) >= 3, f"≥3 inflation releases across DM+EUR (got {len(infl)})")

    print("[7] releases_from_load_results")
    load_results = [
        _make_loadresult("DM_WEEK.txt", SAMPLE_DM),
        _make_loadresult("EUR_WEEK.txt", SAMPLE_EUR),
    ]
    all_from_lr = releases_from_load_results(load_results)
    check(len(all_from_lr) == len(dm_releases) + len(eur_releases),
          "release count matches the sum of per-file extractions")

    print("[8] parse_command")
    cmd = parse_command("QUICK2EUR")
    check(cmd.get("regions") == ["EUR"] and cmd.get("min_importance") == "****",
          "QUICK2EUR → EUR / ****")
    cmd = parse_command("**** inflation EM")
    check(cmd.get("min_importance") == "****", "**** flag parsed")
    check("Inflation" in cmd.get("themes", []), "'inflation' theme parsed")
    check("EM" in cmd.get("regions", []), "EM region parsed")
    cmd = parse_command("CPI AUD")
    check("AUD" in cmd.get("regions", []), "AUD region parsed from 'CPI AUD'")
    check(cmd.get("query", "").lower() == "cpi", "CPI flows into query")

    print()
    if failures:
        print(f"FAILED — {len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All smoke-test checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
