"""Regression tests for tasks #60-#63: title selection must come from the
real release header (country-dashed line), never from analyst commentary
that happens to precede or share the paragraph.

Live-screenshot bugs reproduced here:
  1. "Gating: next retail print and CPI composition determine whether this
     is a trend or a pull-forward payback." -- analyst stub.
  2. "Helps keep the 'cuts later in year' scenario alive, but CPI services
     is still the gate." -- analyst stub.
  3. "It does not overturn the broader US activity floor, but it makes the
     pricing path harder." -- analyst stub.
  4. "Markets can read this as relative German resilience, but for the ECB
     the more important information is the price and supply-chain side,
     not the headline activity index." -- commentary that happens to mention
     "German" (matches the Germany alias) and was outranking the real
     country-dashed title that followed.

In every case the parser must return the country-dashed release header as
the title, not the commentary line.
"""
import sys
import os as _os

_REPO_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.parsers import (
    Block,
    extract_releases,
    _best_title_line,
    _looks_like_preamble,
    _looks_like_release_title,
)

PASS = 0
FAIL = 0
def expect(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok - {label}")
    else:
        FAIL += 1
        print(f"  FAIL - {label}  {detail}")


# ---------------------------------------------------------------------------
# 1. _looks_like_preamble: analyst stubs do NOT qualify, even when short.
# ---------------------------------------------------------------------------
ANALYST_STUBS = [
    "Gating: next retail print and CPI composition determine.",
    "JGM note: this aligns with the prior week.",
    "Helps keep the 'cuts later in year' scenario alive.",
    "Signal: tighter financial conditions.",
    "Takeaway: stagflation reinforced.",
    "Macro configuration: restrictive hold.",
    "It does not overturn the broader US activity floor.",
    "This does not change the policy stance.",
    "The print remained mixed.",
    "The release reads softer at the margin.",
    "The broader trend stayed intact.",
    "The key signal was tighter margin.",
    "In short, growth is fine.",
    "Supports 'Fed can wait': no external inflation forcing hand.",
]
for stub in ANALYST_STUBS:
    expect(f"preamble rejects analyst stub {stub[:40]!r}",
           not _looks_like_preamble(stub),
           "got True (would hijack title)")
    expect(f"_looks_like_release_title rejects {stub[:40]!r}",
           not _looks_like_release_title(stub),
           "got True (strict pass would pick stub)")

# Real release titles must still pass both checks.
REAL_TITLES = [
    "United States - CPI (Mar)",
    "UNITED STATES \u2014 GDP 2nd Estimate (Q4)",
    "Australia - GDP (Q1)",
    "Euro Zone \u2014 HCOB Mfg Final PMI (Mar)",
    "Germany \u2014 Ifo Business Climate (Apr)",
]
for title in REAL_TITLES:
    expect(f"_looks_like_release_title accepts {title!r}",
           _looks_like_release_title(title))
    expect(f"preamble accepts real title {title!r}",
           _looks_like_preamble(title))


# ---------------------------------------------------------------------------
# 2. _best_title_line two-pass: country-dashed line wins even if it isn't
#    the first line of the paragraph.
# ---------------------------------------------------------------------------
PARA = (
    "Markets can read this as relative German resilience, but for the ECB the "
    "more important information is the price and supply-chain side, not the "
    "headline activity index.\n"
    "Euro Zone \u2014 HCOB Mfg Final PMI (Mar)\n"
    "Release Date: 1 Apr 2026 | Local Time: 10:00\n"
    "Importance: ****\n"
    "Reuters Data\n"
    "HCOB Mfg Final PMI: 51.6 | Prior: 51.4 | Poll: 51.4 | Surprise: 0.20"
)
got = _best_title_line(PARA)
expect("commentary-then-real-title paragraph picks Euro Zone",
       got == "Euro Zone \u2014 HCOB Mfg Final PMI (Mar)",
       f"got {got!r}")

# Pure commentary (no country-dashed title) still falls back to the looser
# title check so we don't break the existing fixtures that lack a header.
PARA_NO_HEADER = (
    "United States - CPI (Mar)\n"
    "Release Date: 15 Apr 2026\n"
    "Importance: ****"
)
got2 = _best_title_line(PARA_NO_HEADER)
expect("country-dashed first line picked",
       got2 == "United States - CPI (Mar)", f"got {got2!r}")


# ---------------------------------------------------------------------------
# 3. End-to-end: the four bug examples produce country-dashed titles, not
#    the commentary that precedes them.
# ---------------------------------------------------------------------------
BUG_BLOCKS = [
    # Gating: stub
    (
        "Gating: next retail print and CPI composition determine whether this "
        "is a trend or a pull-forward payback.\n"
        "United States \u2014 Employment Cost Index (Q4)\n"
        "Release Date: 10 Feb 2026 | Local Time: 14:30 EST\n"
        "Importance: ***\n"
        "Reuters Data\n"
        "QoQ: +0.7% | Prior: +0.8%",
        "United States \u2014 Employment Cost Index (Q4)",
    ),
    # Helps keep stub
    (
        "Helps keep the 'cuts later in year' scenario alive, but CPI services "
        "is still the gate.\n"
        "United States \u2014 Employment Report (NFP, Jan)\n"
        "Release Date: 11 Feb 2026 | Local Time: 14:30 EST\n"
        "Importance: ****\n"
        "Reuters Data\n"
        "NFP: +130k | Prior: +50k",
        "United States \u2014 Employment Report (NFP, Jan)",
    ),
    # It does not stub
    (
        "It does not overturn the broader US activity floor.\n"
        "UNITED STATES \u2014 GDP 2nd Estimate (Q4)\n"
        "Release Date: 27 Feb 2026 | Local Time: 13:30\n"
        "Importance: ****\n"
        "Reuters Data\n"
        "GDP QoQ: 2.4% | Prior: 2.4%",
        "UNITED STATES \u2014 GDP 2nd Estimate (Q4)",
    ),
    # German-resilience commentary
    (
        "Markets can read this as relative German resilience, but for the ECB "
        "the more important information is the price and supply-chain side, "
        "not the headline activity index.\n"
        "Euro Zone \u2014 HCOB Mfg Final PMI (Mar)\n"
        "Release Date: 1 Apr 2026 | Local Time: 10:00\n"
        "Importance: ****\n"
        "Reuters Data\n"
        "HCOB Mfg Final PMI: 51.6 | Prior: 51.4",
        "Euro Zone \u2014 HCOB Mfg Final PMI (Mar)",
    ),
]
for raw_text, want in BUG_BLOCKS:
    b = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=raw_text)
    rels = extract_releases(b)
    expect(f"one release parsed for {want[:50]!r}",
           len(rels) == 1, f"got {len(rels)}")
    if rels:
        expect(f"title is {want!r}",
               rels[0].title == want,
               f"got {rels[0].title!r}")


# ---------------------------------------------------------------------------
# 4. Two real releases separated by a blank line, the second preceded by
#    an analyst stub. Both must parse and the second must NOT inherit the
#    stub.
# ---------------------------------------------------------------------------
TWO_RELEASE = """\
United States - CPI (Mar) ****

Release Date: 15 Apr 2026
Importance: 4

Reuters Data: Headline 2.6% YoY.

Gating: next retail print and CPI composition determine whether this is a trend or a pull-forward payback.

United States \u2014 Employment Cost Index (Q4) ***

Release Date: 10 Feb 2026
Importance: 3

Reuters Data: QoQ: +0.7% | Prior: +0.8%
"""
b2 = Block(stem="USD_WEEK", source_file="USD_WEEK.txt", raw_text=TWO_RELEASE)
rels2 = extract_releases(b2)
titles2 = [r.title for r in rels2]
expect("two releases parsed", len(rels2) == 2, f"got {len(rels2)} -> {titles2}")
expect("first title is CPI",
       any("CPI" in t for t in titles2), f"got {titles2}")
expect("second title is Employment Cost Index, not 'Gating: ...'",
       any("Employment Cost Index" in t for t in titles2),
       f"got {titles2}")
expect("no analyst stub appears as a release title",
       not any(t.lower().startswith(("gating:", "jgm note", "helps keep",
                                      "signal:", "takeaway:", "it does not",
                                      "this does not"))
               for t in titles2),
       f"got {titles2}")


print(f"\n{PASS} ok, {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
