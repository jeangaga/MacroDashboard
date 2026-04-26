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
    extract_reference_period,
    first_date_string,
    max_importance,
    parse_release_date,
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
    # Greedy `.*` so the block extends to the LAST `<<STEM_END>>` in the
    # file. Some macro-note files use an inner `<<STEM_END>>` as a
    # section divider after the brief summary, then a final
    # `<<<STEM_END>>>` (triple bracket) as the actual terminator. A lazy
    # match would stop at the first inner END and silently drop the
    # detailed sections that follow.
    return re.compile(begin + r"\s*(.*)\s*" + end, re.DOTALL)


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
    # Reference period the release describes (e.g. "2026-03" for CPI (Mar),
    # "2026-Q1" for GDP (Q1)). Independent of release/publication date.
    # None when the title carries no recognizable period token. Used as the
    # catalogue grouping anchor so a delayed revision can't outrank a fresh
    # print for an earlier reference period.
    reference_period: Optional[str] = None

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
    # Analyst stub-prefixes that polluted release titles in older note
    # versions. These never start a real release header.
    "jgm note",
    "gating:",
    "signal:",
    "signal tension",
    "takeaway:",
    "macro configuration",
    "it does not",
    "this does not",
    "the print",
    "the release",
    "the broader",
    "the key",
    "in short",
    "helps keep",
    "supports ",
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


# Synthesis-section dividers used in the new MACRO SYNTHESIS / SCOREBOARD /
# FULL RELEASE ARCHIVE format. Lines like "A. US WEEK — MACRO SYNTHESIS",
# "B. US MACRO SIGNAL SCOREBOARD", "C. FULL RELEASE ARCHIVE" must NEVER be
# treated as release titles, otherwise the first release in the archive
# inherits the synthesis header.
_SYNTHESIS_HEADER_RE = re.compile(
    r"^\s*[A-D]\.\s+.+\b(?:SYNTHESIS|SCOREBOARD|ARCHIVE|SIGNAL\s+SCOREBOARD)\b",
    re.I,
)


def _is_synthesis_header_line(line):
    if not line:
        return False
    return bool(_SYNTHESIS_HEADER_RE.match((line or "").strip()))


def _looks_like_commentary_fragment(line):
    """True when the line looks like prose / commentary, not a release title."""
    s = (line or "").strip()
    if not s:
        return False
    low = s.lower()
    for p in _COMMENTARY_PREFIXES:
        if low.startswith(p):
            return True
    # Long narrative sentence without the country -- indicator structure of a
    # release title.
    has_dash_structure = _TITLE_DASH_RE.search(s) is not None
    has_country = bool(country_from_title(s))
    if not has_dash_structure and not has_country:
        for ph in _NARRATIVE_PHRASES:
            if ph in low:
                return True
        # Heavily prose-like lines (long, many words, no slash list, no
        # country, no dash separator) are commentary.
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
    if _is_synthesis_header_line(s):
        # Synthesis dividers ("A. ... MACRO SYNTHESIS", "B. ... SCOREBOARD",
        # "C. FULL RELEASE ARCHIVE") are section headers, never release titles.
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


def _looks_like_release_title(line):
    """Stricter than _looks_like_title_line: also requires a country-prefixed
    dashed title pattern. Used by the boundary-injection pre-pass to find
    release starts inside dense, blank-line-less blocks.
    """
    s = (line or "").strip()
    if not s:
        return False
    if _is_synthesis_header_line(s):
        return False
    if _is_day_header_line(s):
        return False
    if _looks_like_commentary_fragment(s):
        return False
    if not _TITLE_DASH_RE.search(s):
        return False
    if not country_from_title(s):
        return False
    return True


def _inject_release_boundaries(text):
    """When a block packs multiple releases per paragraph (no blank lines
    between them), insert blank lines before each release boundary so the
    paragraph-based splitter can see them.

    A boundary is:
      - A line that looks like a release title (country-dashed, not a
        synthesis header), AND
      - one of the next ~6 lines contains 'Release Date:'.

    Already-blank-separated boundaries are not duplicated. If the block
    already has roughly one blank line per release the function is a no-op,
    so the older format keeps working unchanged.
    """
    if not text or "Release Date:" not in text:
        return text
    rd_count = text.count("Release Date:")
    blank_paragraphs = len(re.findall(r"\n\s*\n", text))
    # If the block already has at least one blank line per release, the
    # existing paragraph splitter is fine. (We still run for single-release
    # blocks because a synthesis preamble in the same paragraph as the
    # release can leak into the title without the boundary insert.)
    if rd_count and blank_paragraphs >= rd_count:
        return text
    lines = text.split("\n")
    out = []
    n = len(lines)
    for i, line in enumerate(lines):
        boundary = False
        if _looks_like_release_title(line):
            for j in range(i + 1, min(n, i + 7)):
                if "Release Date:" in lines[j]:
                    boundary = True
                    break
        if boundary and out and out[-1].strip():
            out.append("")
        out.append(line)
    return "\n".join(out)


def _looks_like_preamble(paragraph):
    """A paragraph qualifies as a release preamble ONLY when its first
    non-empty line itself looks like a real release title, i.e. has BOTH
    a country prefix AND a dash-indicator structure.

    Older versions accepted any title-passing line under 120 chars, which
    promoted analyst stubs ("Gating: next retail print determines whether
    this is a trend or a pull-forward payback.", "Helps keep the cuts
    later in year scenario alive...") into release titles. The fall-back
    to length is intentionally removed.
    """
    if not paragraph:
        return False
    line = ""
    for raw in paragraph.splitlines():
        if raw.strip():
            line = raw.strip()
            break
    if not _looks_like_title_line(line):
        return False
    if not _TITLE_DASH_RE.search(line):
        return False
    if not country_from_title(line):
        return False
    return True


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
    # Some weekly archives pack multiple releases per block with no blank
    # lines between them (the new MACRO SYNTHESIS / SCOREBOARD / FULL
    # RELEASE ARCHIVE format). Inject blank lines before each release
    # boundary so the paragraph splitter sees them as distinct paragraphs.
    raw_text = _inject_release_boundaries(block.raw_text)
    paragraphs = _PARAGRAPH_SPLIT.split(raw_text)

    groups = []
    current = None
    pending_preamble = None

    for para in paragraphs:
        para = para.strip("\n")
        if not para.strip():
            continue
        # Drop pure day-header paragraphs entirely.
        if _is_day_header_paragraph(para):
            continue
        # If a paragraph mixes a day banner with real content, peel the
        # banner off and keep the rest.
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

        # Real release blocks must have at least one structured signal.
        if not _has_release_signals(full_text):
            continue

        # Title preference order:
        #   1. The flagged release paragraph (header_for_flag) -- this is the
        #      paragraph carrying Release Date / Importance, so its first
        #      country-dashed line is the canonical title.
        #   2. The preamble paragraph (title_source != header_for_flag).
        #   3. Any other paragraph in the group, scanned in order.
        # Older versions ran (2) first, which let analyst stubs ("Gating: ...",
        # "JGM note: ...") hijack the title when they happened to pass the
        # title-line check.
        title = _best_title_line(header_for_flag)
        if not title and title_source is not header_for_flag:
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
        # Reference period: what the release describes ("Mar", "Q1", ...),
        # not when it was published. Year is inferred from the parsed
        # release date so the catalogue can sort/dedup by period rather
        # than by publication date.
        release_date = parse_release_date(date_str) if date_str else None
        reference_period = extract_reference_period(title, release_date)
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
            reference_period=reference_period,
        ))
    return releases


def _best_title_line(paragraph):
    """Pick the best release-title line from a paragraph.

    Two-pass:
      1. Scan for a strict country-dashed release title
         (_looks_like_release_title). This is the canonical release header
         and must always win when present, even if it isn't the first line
         of the paragraph.
      2. Fall back to any line that passes the looser title-line check
         (_looks_like_title_line).

    Older versions ran (2) only, which let commentary lines that happened
    to mention a country (e.g. "Markets can read this as relative German
    resilience...") outrank the real release title that followed.
    """
    if not paragraph:
        return ""
    candidates = [raw.strip() for raw in paragraph.splitlines() if raw.strip()]
    for line in candidates:
        if _looks_like_release_title(line):
            return line
    for line in candidates:
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


_TOP_SECTION_RE = re.compile(r"^([A-D])\.\s+(.+)$")


def split_top_level_sections(block_raw_text):
    """Split a block's raw_text by top-level letter-prefixed sections
    (`A. ...`, `B. ...`, `C. ...`, `D. ...`).

    Each weekly note is structured as:
        A. ... MACRO SYNTHESIS         -- prose
        B. ... SIGNAL SCOREBOARD       -- Growth/Labor/Inflation/...
        C. FULL RELEASE ARCHIVE        -- the actual releases (already
                                          rendered in Weekly Monitor)
        D. ... (optional)

    This helper is letter-only (A through D), so a stray line like
    `Q4. revisions ...` will not be confused for a section header.
    Header line itself is included in the returned `header` field; the
    `body` is everything from after the header up to (but not including)
    the next top-level section header or end of text.

    Returns ordered list of (letter, header_line, body) tuples.
    """
    if not block_raw_text:
        return []
    lines = block_raw_text.splitlines()
    sections = []
    current_letter = None
    current_header = None
    current_body = []
    for line in lines:
        stripped = line.strip()
        m = _TOP_SECTION_RE.match(stripped) if stripped else None
        if m:
            if current_letter is not None:
                sections.append(
                    (current_letter, current_header, "\n".join(current_body).rstrip())
                )
            current_letter = m.group(1).upper()
            current_header = stripped
            current_body = []
        elif current_letter is not None:
            current_body.append(line)
    if current_letter is not None:
        sections.append(
            (current_letter, current_header, "\n".join(current_body).rstrip())
        )
    return sections


def extract_macro_note_blocks(text, source_file):
    """Macro-note-specific extractor.

    Two differences from `extract_blocks(text, source_file)`:
      - `split_weekly=False`: the marker block stays whole even when the
        body contains multiple `Data window:` lines (e.g. a table of
        historical windows that should NOT be treated as version
        separators). Each `<<STEM_BEGIN>>...<<STEM_END>>` pair is one
        complete note version.
      - The block's `data_window` metadata is populated from the LATEST
        `Data window:` line found inside the body. This is for
        sorting/display only -- the body is preserved verbatim.
    """
    blocks = extract_blocks(text, source_file=source_file, split_weekly=False)
    out = []
    for b in blocks:
        windows = find_data_windows(b.raw_text)
        if not windows:
            out.append(b)
            continue
        latest = None
        latest_end = None
        for label, start, end, _ms, _me in windows:
            end_d = parse_release_date(end) if end else None
            if end_d is None:
                continue
            if latest_end is None or end_d > latest_end:
                latest_end = end_d
                latest = (label, start, end)
        if latest is None:
            label, start, end, _ms, _me = windows[-1]
            latest = (label, start, end)
        b.data_window, b.data_window_start, b.data_window_end = latest
        out.append(b)
    return out


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
