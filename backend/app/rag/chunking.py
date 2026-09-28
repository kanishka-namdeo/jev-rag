"""Structure-aware markdown chunking with contextual (title + heading-path) prefixes.

Rationale (contextual retrieval): prepending cheap document context —
"doc title — section heading path" — to every chunk measurably improves
retrieval: Anthropic's contextual-retrieval evidence shows top-20 retrieval
failures dropping 5.7% -> 3.7% with prefix contextualization (49% when
combined with contextual BM25). See docs/rag-upgrade-2026.md section 2.4
(evidence) and section 3.1 (the v3 shared retrieval stack: "markitdown ->
structure-aware split -> contextual prefix -> dense embed"). This module is
the split stage of that design; it replaces the old flat
RecursiveCharacterTextSplitter call in ingestion.py, which had no structure
awareness (audit finding #5).

Public API
----------
``ChunkSpec`` — one chunk: full text (prefix + " :: " + body), section path
string, heading path list, body-only char count.

``split_structure_aware(text, title, chunk_size, overlap)`` — markdown-aware
split (ATX + Setext headings, fenced-code safe) where every chunk text starts
with ``" | ".join([title] + heading_path) + " :: "``.

``split_plain(text, chunk_size, overlap)`` — flat recursive split, no
structure, no prefix (compat wrapper for callers that want the old
ingestion.py behaviour).

Design decisions (documented on purpose)
-----------------------------------------
1. Sections: content before the first heading is the ROOT section
   (``heading_path == []``; prefix = title only). A heading with no body is
   merged FORWARD: its heading joins the *next* section's heading path (so
   "## Empty" / "## Next" / body yields path ["Empty", "Next"]). The merged
   heading becomes an extra path element even when heading levels would not
   nest them — context beats strict level semantics. Trailing heading-only
   sections at EOF have no forward section and are dropped (no content ->
   nothing to index).
2. Prefix budget: chunk text = ``f"{prefix} :: {body}"``; the body budget is
   ``max(200, chunk_size - len(prefix) - 4)`` so a long prefix can never
   shrink bodies below 200 chars. Empty title/path entries are dropped from
   the prefix join (an empty title would otherwise emit a leading " | ").
3. Heading paths are capped to the DEEPEST 3 levels to bound prefix length
   (the title still ships, so context is preserved).
4. Code-fence safety: a chunk boundary never leaves an unbalanced ``` / ~~~
   fence. A piece with an odd count of fence-marker lines is MERGED with the
   next piece of the same section (preferred fix); only the section-FINAL
   piece is auto-closed by appending a literal "\n```" when it still ends
   unbalanced (which only happens when the section itself had an odd number
   of fence markers — malformed markdown).
   Trade-offs, accepted: a merged piece may exceed the body budget, and the
   merge re-includes up to ``overlap`` chars of splitter overlap. Fence
   integrity (balanced markers) wins over strict size/duplication here.
5. Setext headings (text line + "=====" / "-----" underline) are recognized
   because they are common in markdown exports. Detection is the simple
   two-line rule, so a list item directly followed by a thematic break
   "``---``" is (mis)read as a setext-2 heading — rare in markitdown output,
   deterministic, accepted.
6. Within-section splitting uses langchain_text_splitters'
   RecursiveCharacterTextSplitter (an existing project dependency) with the
   same CJK-aware separator ladder as ingestion.py, imported lazily to keep
   module import light.
7. Determinism: ``split_structure_aware`` and ``split_plain`` are pure
   functions of their arguments (no RNG, no clock, no global state).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["ChunkSpec", "split_structure_aware", "split_plain"]

#: Prefix = " | ".join([title] + heading_path); chunk text = prefix + " :: " + body.
_PREFIX_SEP = " | "
_CHUNK_SEP = " :: "
_SECTION_SEP = " > "
#: Heading paths are capped to the deepest 3 levels to bound prefix length.
_PATH_DEPTH_CAP = 3
#: Bodies never shrink below this, however long the prefix gets.
_MIN_BODY = 200

#: CJK-aware separator ladder (mirrors app/rag/ingestion.py).
_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "，", "。", "、", "！", "？", "; ", ", ", " ", ""]

_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SETEXT_EQ_RE = re.compile(r"=+")
_SETEXT_DASH_RE = re.compile(r"-+")


@dataclass
class ChunkSpec:
    """One chunk emitted by :func:`split_structure_aware`.

    Attributes:
        text: final chunk text — ``f"{prefix} :: {body}"`` where
            ``prefix = " | ".join([title] + heading_path)``.
        section: human-readable heading path — ``" > ".join(heading_path)``
            ("" for root sections).
        heading_path: the section's heading chain, capped at the deepest 3
            levels; empty list for root (pre-heading) content.
        char_count: body length WITHOUT the prefix (so downstream ingestion
            can cap total chunk length independently).
    """

    text: str
    section: str
    heading_path: list[str]
    char_count: int


@dataclass
class _RawSection:
    """Parser output: heading path + raw body lines (heading lines excluded)."""

    path: list[str]
    lines: list[str]


# ---------------------------------------------------------------------------
# Structure parsing
# ---------------------------------------------------------------------------


def _is_fence_marker_line(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def _setext_underline_level(line: str) -> int:
    """Return 1 (``=``), 2 (``-``) or 0 (not an underline) for ``line``."""
    stripped = line.strip()
    if stripped and _SETEXT_EQ_RE.fullmatch(stripped):
        return 1
    if stripped and _SETEXT_DASH_RE.fullmatch(stripped):
        return 2
    return 0


def _parse_sections(text: str) -> list[_RawSection]:
    """Single pass over lines: fences, ATX headings, Setext headings, content.

    Fence lines toggle in-fence state; heading detection is IGNORED inside
    fences. Each heading opens a new section carrying the cumulative heading
    path (level n replaces stack entry n and truncates deeper entries).
    """
    lines = text.split("\n")
    sections: list[_RawSection] = [_RawSection(path=[], lines=[])]  # root
    stack: list[str] = []  # index i holds the level-(i+1) heading text
    in_fence = False

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        if in_fence:  # inside a fence: everything is content, no headings
            sections[-1].lines.append(line)
            if _is_fence_marker_line(line):
                in_fence = False
            i += 1
            continue

        if _is_fence_marker_line(line):  # fence opener
            in_fence = True
            sections[-1].lines.append(line)
            i += 1
            continue

        atx = _ATX_HEADING_RE.match(line)
        if atx:  # ATX heading: # .. ######
            level = len(atx.group(1))
            stack = stack[: level - 1] + [atx.group(2).strip()]
            sections.append(_RawSection(path=list(stack), lines=[]))
            i += 1
            continue

        if line.strip():  # Setext candidate: non-empty text line + underline below
            level = _setext_underline_level(lines[i + 1]) if i + 1 < n else 0
            if level:
                stack = stack[: level - 1] + [line.strip()]
                sections.append(_RawSection(path=list(stack), lines=[]))
                i += 2  # consume text + underline
                continue

        sections[-1].lines.append(line)
        i += 1

    return sections


def _fresh_headings(prev_path: list[str], path: list[str]) -> list[str]:
    """Headings ``path`` introduces relative to ``prev_path`` (common prefix stripped)."""
    k = 0
    while k < len(prev_path) and k < len(path) and prev_path[k] == path[k]:
        k += 1
    return path[k:]


def _merge_empty_sections_forward(raw: list[_RawSection]) -> list[tuple[list[str], str]]:
    """Resolve empty sections (see docstring decision 1).

    A section with no body merges its *fresh* headings into the next
    section's path (the carried headings replace the common-prefix part of
    the next section's raw path). A normal section keeps its full stack
    path. Trailing empty sections are dropped.
    """
    merged: list[tuple[list[str], str]] = []
    carry: list[str] = []
    prev_path: list[str] = []
    for sec in raw:
        content = "\n".join(sec.lines).strip()
        fresh = _fresh_headings(prev_path, sec.path)
        if not content:
            carry.extend(fresh)  # heading with no body -> context for next section
        else:
            merged.append((carry + fresh if carry else list(sec.path), content))
            carry = []
        prev_path = sec.path
    return merged


# ---------------------------------------------------------------------------
# Code-fence balancing
# ---------------------------------------------------------------------------


def _count_fence_markers(piece: str) -> int:
    return sum(1 for line in piece.split("\n") if _is_fence_marker_line(line))


def _balance_code_fences(pieces: list[str]) -> list[str]:
    """Never leave a chunk with an unbalanced ``` / ~~~ fence.

    Preferred fix: MERGE a piece whose fence-marker count is odd with the
    next piece of the same section (joined with a blank line). Only the
    section-final piece gets an appended closing fence ("\n```") when it
    still ends unbalanced — this happens only when the section itself had an
    odd number of fence markers (malformed markdown).
    """
    balanced: list[str] = []
    buf: str | None = None
    for piece in pieces:
        buf = piece if buf is None else f"{buf}\n\n{piece}"
        if _count_fence_markers(buf) % 2 == 0:
            balanced.append(buf)
            buf = None
    if buf is not None:
        if _count_fence_markers(buf) % 2 == 1:
            buf = f"{buf}\n```"  # auto-close the section-final unbalanced fence
        balanced.append(buf)
    return balanced


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def _make_splitter(chunk_size: int, chunk_overlap: int):
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # lazy: keep import light

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_SEPARATORS,
    )


def _effective_overlap(overlap: int, budget: int) -> int:
    return max(0, min(overlap, budget - 1))


def split_structure_aware(
    text: str,
    title: str,
    chunk_size: int = 900,
    overlap: int = 140,
) -> list[ChunkSpec]:
    """Structure-aware markdown split with contextual prefixes.

    Args:
        text: markdown document (markitdown output or raw markdown).
        title: document title; becomes the first prefix element.
        chunk_size: target TOTAL chunk size (prefix + " :: " + body).
        overlap: character overlap between consecutive bodies of a section.

    Returns:
        Chunks whose ``text`` starts with ``" | ".join([title] +
        heading_path) + " :: "``; ``char_count`` counts the body only.
        Deterministic pure function of the arguments.
    """
    if not text or not text.strip():
        return []

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    chunks: list[ChunkSpec] = []
    for path, content in _merge_empty_sections_forward(_parse_sections(text)):
        capped = path[-_PATH_DEPTH_CAP:]
        parts = [p for p in ([title] + capped) if p]
        prefix = _PREFIX_SEP.join(parts)
        body_budget = max(_MIN_BODY, chunk_size - len(prefix) - len(_CHUNK_SEP))

        splitter = _make_splitter(body_budget, _effective_overlap(overlap, body_budget))
        pieces = _balance_code_fences(splitter.split_text(content))

        for piece in pieces:
            body = piece.strip()
            chunks.append(
                ChunkSpec(
                    text=f"{prefix}{_CHUNK_SEP}{body}" if prefix else body,
                    section=_SECTION_SEP.join(capped),
                    heading_path=list(capped),
                    char_count=len(body),
                )
            )
    return chunks


def split_plain(text: str, chunk_size: int = 900, overlap: int = 140) -> list[str]:
    """Flat recursive split — legacy ingestion.py behaviour.

    No markdown structure awareness, no contextual prefix. Compat wrapper
    for callers that want the old chunking semantics.
    """
    if not text or not text.strip():
        return []
    splitter = _make_splitter(chunk_size, _effective_overlap(overlap, chunk_size))
    return splitter.split_text(text)
