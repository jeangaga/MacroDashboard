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
    # Top-level weekly-note section this release was parsed from
    # ("data" for the normal release stream, "central_bank_tape" for ECB/Fed
    # speaker-tape items, "synthesis"/"signal_tension"/"key_releases"/
    # "red_team" for the named narrative sections). The Weekly Monitor groups
    # "central_bank_tape" releases into a single card instead of peer cards.
    section: str = "data"

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


# Top-level section headers in the evolved weekly format. A note is laid out:
#   A. <SCOPE> WEEK - MACRO SYNTHESIS
#   B. <SCOPE> MACRO SIGNAL SCOREBOARD
#   CENTRAL BANK TAPE              (optional; absent in some versions / DM-EM)
#   SIGNAL TENSION CHECK
#   N KEY RELEASES TO DIG INTO     (N = 3 or 5 depending on version)
#   RED TEAM QUESTIONS FOR JGM / SECOND PASS SCOUT   (optional)
# These standalone ALL-CAPS headers delimit sections: a release's commentary
# must never run past one of them (that bug let a data release swallow the
# CENTRAL BANK TAPE summary), and CENTRAL BANK TAPE content is grouped rather
# than shown as peer release cards.
_WEEKLY_SECTION_NAME_RES = [
    ("central_bank_tape", re.compile(r"^CENTRAL\s+BANK\s+TAPE\b")),
    ("signal_tension",    re.compile(r"^SIGNAL\s+TENSION\s+CHECK\b")),
    ("key_releases",      re.compile(r"^\d+\s+KEY\s+RELEASES\s+TO\s+DIG\s+INTO\b")),
    ("red_team",          re.compile(r"^(?:RED\s+TEAM\s+QUESTIONS|SECOND\s+PASS\s+SCOUT)\b")),
]


def _is_upper_header(s):
    """True for a short, standalone, ALL-CAPS header line (digits/punctuation
    allowed, but no lowercase letters). This distinguishes a top-level section
    header ("SIGNAL TENSION CHECK") from a per-release title-cased commentary
    label ("Signal Tension Check: ...") that older notes attach to a release.
    """
    s = (s or "").strip()
    if not s or len(s) > 70:
        return False
    if any(ch.islower() for ch in s):
        return False
    return any(ch.isalpha() for ch in s)


def weekly_section_of(line):
    """Return the section id for a top-level weekly section header line, else
    None. Synthesis dividers (A./B./C. ... SYNTHESIS/SCOREBOARD/ARCHIVE) map to
    'synthesis'. Named sections must be ALL-CAPS to count as a boundary.
    """
    s = (line or "").strip()
    if not s:
        return None
    if _is_synthesis_header_line(s):
        return "synthesis"
    if not _is_upper_header(s):
        return None
    for sid, pat in _WEEKLY_SECTION_NAME_RES:
        if pat.match(s):
            return sid
    return None


def _isolate_section_headers(text):
    """Ensure every top-level weekly section header sits on its own paragraph
    by surrounding it with blank lines. Lets the paragraph splitter see the
    header as a distinct boundary even in dense, blank-line-poor blocks."""
    if not text:
        return text
    lines = text.split("\n")
    out = []
    for line in lines:
        if weekly_section_of(line):
            if out and out[-1].strip():
                out.append("")
            out.append(line)
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def extract_central_bank_tape_text(block):
    """Return the raw text of the CENTRAL BANK TAPE section of a weekly block
    (everything after its header up to the next top-level section header), or
    "" when the block has no CENTRAL BANK TAPE section.
    """
    if not block or not block.raw_text:
        return ""
    lines = block.raw_text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if weekly_section_of(line) == "central_bank_tape":
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        sec = weekly_section_of(lines[j])
        if sec is not None and sec != "central_bank_tape":
            end = j
            break
    return "\n".join(lines[start + 1:end]).strip()


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
    # First inject blank lines before dense release boundaries (so blocks
    # packing multiple releases per paragraph split correctly), THEN isolate
    # top-level section headers (CENTRAL BANK TAPE, SIGNAL TENSION CHECK, ...)
    # onto their own paragraphs so they act as hard release boundaries: a
    # release's commentary must never run into the next section. Order
    # matters -- isolating first would inflate the blank-line count that the
    # injection heuristic uses to detect dense blocks, disabling it.
    raw_text = _inject_release_boundaries(block.raw_text)
    raw_text = _isolate_section_headers(raw_text)
    paragraphs = _PARAGRAPH_SPLIT.split(raw_text)

    groups = []            # list of (group_paragraphs, section_id)
    current = None
    current_section = "data"   # section the currently-open group belongs to
    active_section = "data"    # section being scanned right now
    pending_preamble = None

    for para in paragraphs:
        para = para.strip("\n")
        if not para.strip():
            continue
        # A standalone top-level section header closes any open release
        # (commentary never bleeds across sections) and switches the active
        # section. The header itself is not part of any release.
        meaningful = [ln for ln in para.splitlines() if ln.strip()]
        if len(meaningful) == 1:
            sec = weekly_section_of(meaningful[0])
            if sec is not None:
                if current is not None:
                    groups.append((current, current_section))
                    current = None
                pending_preamble = None
                active_section = sec
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
        # A paragraph only STARTS a new release if it carries a real release
        # signal (a "Release Date:" / "Importance:" field line, or a
        # country-dashed title). A bare asterisk is NOT enough: commentary
        # bullet lists ("Signal hierarchy:\n* Tokyo core CPI: downside surprise
        # \n* ...") begin with "*", which max_importance reads as a "*"
        # importance flag. Without this guard those bullets split the release,
        # truncating it (the block was being cut off at "Signal hierarchy:" and
        # everything after -- bullets, State transition, HF Take -- was dropped
        # as a signal-less group). Every genuine importance marker
        # ("Importance: ****" line or a "*** Country - Title" header) also
        # satisfies _has_release_signals, so real releases are unaffected.
        flag = max_importance(para)
        if flag is not None and _has_release_signals(para):
            promoted = None
            if (
                current is not None
                and len(current) >= 2
                and max_importance(current[-1]) is None
                and _looks_like_preamble(current[-1])
            ):
                promoted = current.pop()
            if current is not None:
                groups.append((current, current_section))
            if promoted is not None:
                current = [promoted, para]
            elif pending_preamble is not None:
                current = [pending_preamble, para]
            else:
                current = [para]
            current_section = active_section
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
        groups.append((current, current_section))

    releases = []
    region = block.region
    kind = block.kind
    for group, group_section in groups:
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
            section=group_section,
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


# A scoreboard signal line in section B, e.g. "Growth: -", "Labor: +",
# "Inflation: ~". The note already encodes the direction as a +/-/~ glyph, so
# no mapping is needed -- we surface the glyph verbatim.
_SCOREBOARD_SIGNAL_RE = re.compile(
    r"^\s*(Growth|Labou?r|Inflation)\s*:\s*([-+~])\s*$", re.I
)


def extract_week_summary(block):
    """Extract the narrative summary of a weekly block for the Weekly Monitor
    summary expander.

    Returns a dict:
        {
          "signals":  [(name, glyph), ...]   # Growth / Labor / Inflation, in
                                              # that order, read from section B.
          "sections": [(header_line, body), ...]   # A (Macro Synthesis),
                                              # B (Signal Scoreboard), SIGNAL
                                              # TENSION CHECK, N KEY RELEASES TO
                                              # DIG INTO and RED TEAM / SECOND
                                              # PASS (if present), in document
                                              # order. Excludes the release
                                              # archive (C/D) and CENTRAL BANK
                                              # TAPE, which are rendered as
                                              # their own cards.
        }
    """
    empty = {"signals": [], "sections": []}
    if not block or not block.raw_text:
        return empty
    lines = block.raw_text.splitlines()

    # Locate every top-level header: letter sections (A-D) and the named
    # narrative sections. Letter prefix wins, so "C. FULL RELEASE ARCHIVE"
    # is tagged "letter:C" rather than the "synthesis" id weekly_section_of
    # would give it.
    headers = []  # (line_index, kind, header_text)
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = _TOP_SECTION_RE.match(s)
        if m:
            headers.append((i, "letter:" + m.group(1).upper(), s))
            continue
        sec = weekly_section_of(line)
        if sec in ("central_bank_tape", "signal_tension", "key_releases", "red_team"):
            headers.append((i, sec, s))

    # Slice each header's body up to the next header.
    spans = []
    for k, (idx, kind, hdr) in enumerate(headers):
        end = headers[k + 1][0] if k + 1 < len(headers) else len(lines)
        body = "\n".join(lines[idx + 1:end]).strip()
        spans.append((kind, hdr, body))

    # Scoreboard glyphs from section B (first occurrence of each signal wins).
    b_body = next((body for kind, _h, body in spans if kind == "letter:B"), "")
    found = {}
    for bl in b_body.splitlines():
        sm = _SCOREBOARD_SIGNAL_RE.match(bl)
        if sm:
            name = "Labor" if sm.group(1).lower().startswith("labo") else sm.group(1).title()
            found.setdefault(name, sm.group(2))
    signals = [(n, found[n]) for n in ("Growth", "Labor", "Inflation") if n in found]

    # Narrative sections to surface, in document order.
    wanted = {"letter:A", "letter:B", "signal_tension", "key_releases", "red_team"}
    sections = [(hdr, body) for kind, hdr, body in spans if kind in wanted]
    return {"signals": signals, "sections": sections}


# A full section-B scoreboard signal line, e.g. "Growth: ~", "Labor: -",
# "Financial Conditions: ~", "Policy Constraint: +". The glyph (+/-/~) encodes
# direction; "?" is tolerated for an unscored signal.
_SCOREBOARD_DETAIL_RE = re.compile(
    r"^\s*(Growth|Labou?r|Inflation|Financial\s+Conditions|Policy\s+Constraint)"
    r"\s*:\s*([-+~?])\s*$",
    re.I,
)


def _canonical_signal_name(raw):
    low = (raw or "").strip().lower()
    if low.startswith("labo"):
        return "Labor"
    if low.startswith("financial"):
        return "Financial Conditions"
    if low.startswith("policy"):
        return "Policy Constraint"
    if low.startswith("growth"):
        return "Growth"
    if low.startswith("inflation"):
        return "Inflation"
    return (raw or "").strip()


def extract_macro_synthesis(block):
    """Pull section A (Macro Synthesis prose) and the per-signal detail of
    section B (Signal Scoreboard) out of one weekly block, for the cross-week
    Macro Synthesis view.

    Returns:
        {
          "synthesis_header": "A. <SCOPE> WEEK — MACRO SYNTHESIS" or "",
          "synthesis":        "<section A prose>" or "",
          "signals":          [(name, glyph, evidence_body), ...]  # section B,
                              # in document order. `name` is canonicalised
                              # (Growth / Labor / Inflation / Financial
                              # Conditions / Policy Constraint); `evidence_body`
                              # is everything under the signal line (the
                              # "Supporting evidence:" label + paragraph) up to
                              # the next signal line.
        }
    """
    result = {"synthesis_header": "", "synthesis": "", "signals": []}
    if not block or not block.raw_text:
        return result
    b_body = ""
    for letter, header, body in split_top_level_sections(block.raw_text):
        if letter == "A":
            result["synthesis_header"] = header
            result["synthesis"] = body
        elif letter == "B":
            b_body = body
    signals = []
    for line in b_body.splitlines():
        m = _SCOREBOARD_DETAIL_RE.match(line)
        if m:
            signals.append([_canonical_signal_name(m.group(1)), m.group(2), []])
        elif signals:
            signals[-1][2].append(line)
    result["signals"] = [
        (name, glyph, "\n".join(lines).strip()) for name, glyph, lines in signals
    ]
    return result


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
    return _annotate_latest_window(blocks)


def _annotate_latest_window(blocks):
    """Populate each block's primary `data_window` from the LATEST
    `Data window:` line found in its body. Blocks with no window are left
    unchanged. The body is never modified. Returns the same list."""
    for b in blocks:
        windows = find_data_windows(b.raw_text)
        if not windows:
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
    return blocks


# END marker tolerant of 2+ brackets on each side: `<<STEM_END>>` (inner
# divider) and `<<<STEM_END>>>` (real terminator) both match.
def _macro_end_regex(stem):
    return re.compile(r"<{2,}\s*" + re.escape(stem + "_END") + r"\s*>{2,}")


def _macro_begin_regex(stem):
    return re.compile(re.escape(MARKER_PREFIX + stem + "_BEGIN" + MARKER_SUFFIX))


def extract_macro_note_versions(text, source_file):
    """Split a macro-note file into one Block per note VERSION.

    A version starts at each `<<STEM_BEGIN>>` marker and runs to the next
    `<<STEM_BEGIN>>` (or end of file). This is the correct unit for the
    Macro Notes tab: unlike `extract_blocks(split_weekly=True)` it does NOT
    fragment a version at internal `Data window:` lines, and unlike the
    greedy single-block parse it does NOT merge consecutive versions into
    one block (which previously made "Latest note only" bleed the next
    version's `<<END>>`/`<<BEGIN>>` markers and body into the view).

    Within a version an inner `<<STEM_END>>` (double bracket) may act as a
    brief/detail divider; the final END marker (double or triple bracket)
    before the next BEGIN terminates the body. All END marker lines are
    stripped from the displayed body, but the surrounding content -- and any
    `Data window:` table -- is preserved verbatim. Each block's primary
    window metadata is the latest `Data window:` line in its body.
    """
    if not text:
        return []
    # Pick the stem whose BEGIN marker actually appears in the file; fall
    # back to the filename-derived stem.
    stem = None
    for cand in _all_known_stems():
        if (MARKER_PREFIX + cand + "_BEGIN" + MARKER_SUFFIX) in text:
            stem = cand
            break
    if stem is None:
        stem = _stem_from_filename(source_file)

    begin_re = _macro_begin_regex(stem)
    end_re = _macro_end_regex(stem)
    begins = [m.start() for m in begin_re.finditer(text)]

    if not begins:
        body = text.strip()
        if not body:
            return []
        return _annotate_latest_window(
            [Block(stem=stem, source_file=source_file, raw_text=body)]
        )

    out = []
    for i, bpos in enumerate(begins):
        seg_end = begins[i + 1] if i + 1 < len(begins) else len(text)
        segment = text[bpos:seg_end]
        # Drop the leading BEGIN marker.
        segment = begin_re.sub("", segment, count=1)
        # Cut at the LAST END marker in the segment, dropping the terminator
        # and any trailing junk before the next version.
        ends = list(end_re.finditer(segment))
        if ends:
            segment = segment[: ends[-1].start()]
        # Remove any remaining inner END marker lines, keep their content.
        body = end_re.sub("", segment).strip()
        if not body:
            continue
        out.append(Block(stem=stem, source_file=source_file, raw_text=body))
    return _annotate_latest_window(out)


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
