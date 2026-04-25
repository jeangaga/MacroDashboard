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
    first_date_string,
    max_importance,
)


@dataclass
class Block:
    stem: str
    source_file: str
    raw_text: str

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
    return re.compile(begin + r"\s*(.*?)\s*" + end, re.DOTALL)


def extract_blocks(text: str, source_file: str):
    if not text:
        return []
    blocks = []
    for stem in _all_known_stems():
        pat = _marker_regex(stem)
        for m in pat.finditer(text):
            inner = m.group(1)
            if inner.strip():
                blocks.append(Block(stem=stem, source_file=source_file, raw_text=inner))
    if blocks:
        return blocks
    stem = _stem_from_filename(source_file)
    return [Block(stem=stem, source_file=source_file, raw_text=text)]


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

    @property
    def importance_rank(self) -> int:
        return len(self.importance) if self.importance else 0


_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")

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
)


def _looks_like_title_line(line):
    """Heuristic: is this an actual heading rather than a metadata key?"""
    s = (line or "").strip()
    if not s:
        return False
    low = s.lower()
    for p in _TITLE_SKIP_PREFIXES:
        if low.startswith(p):
            return False
    if len(s) > 220:
        return False
    return True


def _looks_like_preamble(paragraph):
    """A short un-flagged paragraph that should be promoted to title for the
    next group."""
    if not paragraph:
        return False
    line = ""
    for raw in paragraph.splitlines():
        if raw.strip():
            line = raw.strip()
            break
    if not _looks_like_title_line(line):
        return False
    if any(sep in line for sep in (" \u2014 ", " \u2013 ", " - ", " -- ")):
        return True
    if country_from_title(line):
        return True
    return len(line) <= 120


def extract_releases(block):
    """Split a block into releases.

    A release starts at a paragraph containing an importance flag.
    All subsequent un-flagged paragraphs are commentary.

    Special case: a short un-flagged paragraph that immediately PRECEDES a
    flagged paragraph is treated as the actual release TITLE (e.g. PM-style
    layout where the title sits one paragraph above the 'Release Date: ...'
    metadata block).
    """
    if not block.raw_text:
        return []
    paragraphs = _PARAGRAPH_SPLIT.split(block.raw_text)

    groups = []
    current = None
    pending_preamble = None

    for para in paragraphs:
        para = para.strip("\n")
        if not para.strip():
            continue
        flag = max_importance(para)
        if flag is not None:
            # If the last paragraph appended to `current` is a preamble for
            # THIS new release, peel it off the prior group.
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

        title = _best_title_line(title_source)
        if not title:
            for para in group:
                cand = _best_title_line(para)
                if cand:
                    title = cand
                    break

        date_str = first_date_string(full_text)
        countries = country_from_title(title)
        themes = detect_themes(full_text)
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
        ))
    return releases


def _best_title_line(paragraph):
    """First line of `paragraph` that doesn't look like metadata."""
    if not paragraph:
        return ""
    for raw in paragraph.splitlines():
        line = raw.strip()
        if not line:
            continue
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
