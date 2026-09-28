"""Tests for app.rag.chunking — structure-aware markdown splitter.

Run: cd backend && .venv/bin/python -m pytest tests/test_chunking.py -v

No models, no network, no app config needed (chunking.py is stdlib +
langchain_text_splitters only).
"""
from __future__ import annotations

from app.rag.chunking import ChunkSpec, split_plain, split_structure_aware

DOC = "Sample Guide"


def _para(tag: str, sentences: int = 30) -> str:
    return " ".join(
        f"{tag} sentence {i} discusses retrieval quality and grounding." for i in range(sentences)
    )


MARKDOWN = f"""{_para("Intro")}

# Root Section

{_para("Root")}

## Alpha

{_para("AlphaOne")}
{_para("AlphaTwo")}

### Deep Dive

{_para("Deep")}

## Beta

{_para("Beta")}
"""


def _fence_marker_count(chunk_text: str) -> int:
    body = chunk_text.split(" :: ", 1)[1] if " :: " in chunk_text else chunk_text
    return sum(
        1 for line in body.split("\n") if line.lstrip().startswith(("```", "~~~"))
    )


def test_structure_aware_prefixes_and_heading_paths():
    chunks = split_structure_aware(MARKDOWN, DOC)
    assert chunks, "must produce chunks"

    # "## Alpha" nests under "# Root Section"; pre-heading content is root.
    expected = {
        (): f"{DOC}",
        ("Root Section",): f"{DOC} | Root Section",
        ("Root Section", "Alpha"): f"{DOC} | Root Section | Alpha",
        ("Root Section", "Alpha", "Deep Dive"): f"{DOC} | Root Section | Alpha | Deep Dive",
        ("Root Section", "Beta"): f"{DOC} | Root Section | Beta",
    }
    seen: set[tuple[str, ...]] = set()
    for ch in chunks:
        assert isinstance(ch, ChunkSpec)
        key = tuple(ch.heading_path)
        assert key in expected, f"unexpected heading_path: {ch.heading_path}"
        prefix = expected[key]
        # every chunk text starts with the full contextual prefix + separator
        assert ch.text.startswith(f"{prefix} :: ")
        assert ch.section == " > ".join(ch.heading_path)
        # body = text minus prefix/separator; char_count counts body only
        body = ch.text[len(prefix) + 4 :]
        assert ch.char_count == len(body)
        assert body.strip()
        # size budgets: body fits the prefix-discounted budget, total is close
        assert ch.char_count <= max(200, 900 - len(prefix) - 4)
        assert len(ch.text) <= 900 + 60
        seen.add(key)
    assert seen == set(expected), f"missing sections: {set(expected) - seen}"

    # a long section actually splits into multiple prefixed chunks
    alpha_chunks = [c for c in chunks if c.heading_path == ["Root Section", "Alpha"]]
    assert len(alpha_chunks) >= 2


def test_code_fence_never_unbalanced_and_headings_ignored_inside_fence():
    code_body = "\n".join(
        f"result_{i} = transform_{i}(payload, mode={i % 7})  # step {i}" for i in range(90)
    )
    doc = (
        "# Code Section\n\n"
        "Intro sentence about the code.\n\n"
        "```python\n"
        "## Fake Heading Inside Fence\n"
        f"{code_body}\n"
        "```\n\n"
        "Outro sentence after the code.\n"
    )
    chunks = split_structure_aware(doc, "Fences", chunk_size=300, overlap=30)
    assert len(chunks) >= 2  # intro / fence / outro (or more) — not one blob
    for ch in chunks:
        # heading detection ignored inside fences: every chunk stays in the section
        assert ch.heading_path == ["Code Section"]
        assert ch.text.startswith("Fences | Code Section :: ")
        # no chunk leaves an unbalanced fence: even count of fence-marker lines
        assert _fence_marker_count(ch.text) % 2 == 0, f"unbalanced fence in: {ch.text[:120]!r}"
    # the fake heading must not have leaked into any prefix
    assert all("Fake" not in ch.text.split(" :: ", 1)[0] for ch in chunks)
    # the fence content itself survived
    assert any("result_89" in ch.text for ch in chunks)


def test_setext_headings_recognized():
    doc = "Setext Title\n===========\n\nBody one.\n\nSub Head\n--------\n\nBody two.\n"
    chunks = split_structure_aware(doc, DOC)
    assert len(chunks) == 2
    assert chunks[0].heading_path == ["Setext Title"]
    assert chunks[0].text == f"{DOC} | Setext Title :: Body one."
    # "-----" underline is a level-2 setext heading -> nests under the level-1
    assert chunks[1].heading_path == ["Setext Title", "Sub Head"]
    assert chunks[1].text == f"{DOC} | Setext Title | Sub Head :: Body two."


def test_heading_only_section_merges_forward():
    doc = "## Empty\n\n## Next\n\nBody under next.\n"
    chunks = split_structure_aware(doc, DOC)
    assert len(chunks) == 1
    assert chunks[0].heading_path == ["Empty", "Next"]
    assert chunks[0].section == "Empty > Next"
    assert chunks[0].text == f"{DOC} | Empty | Next :: Body under next."


def test_no_headings_prefix_is_title_only():
    doc = "\n\n".join(_para("Plain", 20) for _ in range(4))
    chunks = split_structure_aware(doc, DOC, chunk_size=400, overlap=50)
    assert len(chunks) > 1
    for ch in chunks:
        assert ch.heading_path == []
        assert ch.section == ""
        assert ch.text.startswith(f"{DOC} :: ")


def test_cjk_sections_split_with_prefix():
    cjk_body = (
        "检索增强生成把大模型与外部知识库结合起来。"
        "上下文前缀能显著降低检索失败率。"
        "混合检索同时利用稀疏与稠密信号。"
        "重排序器进一步提升了排序质量。"
    ) * 8
    doc = f"# 中文章节\n\n{cjk_body}"
    prefix = f"中文文档 | 中文章节"
    chunks = split_structure_aware(doc, "中文文档", chunk_size=300, overlap=40)
    assert len(chunks) >= 2
    for ch in chunks:
        assert ch.heading_path == ["中文章节"]
        assert ch.text.startswith(f"{prefix} :: ")
        assert "检索" in ch.text
        assert ch.char_count <= max(200, 300 - len(prefix) - 4)


def test_empty_and_tiny_inputs():
    assert split_structure_aware("", DOC) == []
    assert split_structure_aware("   \n\n \t \n", DOC) == []
    assert split_structure_aware("# Just A Heading\n", DOC) == []

    chunks = split_structure_aware("tiny body", DOC)
    assert len(chunks) == 1
    assert chunks[0].text == f"{DOC} :: tiny body"
    assert chunks[0].char_count == len("tiny body")
    assert chunks[0].heading_path == []


def test_deep_heading_path_capped_to_three():
    doc = (
        "# Level One\n\nintro text.\n\n"
        "## Level Two\n\nmore text.\n\n"
        "### Level Three\n\nsome text.\n\n"
        "#### Level Four\n\nfurther text.\n\n"
        "##### Level Five\n\ndeep body text.\n"
    )
    chunks = split_structure_aware(doc, DOC)
    deep = [c for c in chunks if "deep body text" in c.text]
    assert len(deep) == 1
    assert deep[0].heading_path == ["Level Three", "Level Four", "Level Five"]
    assert deep[0].section == "Level Three > Level Four > Level Five"
    assert deep[0].text.startswith(f"{DOC} | Level Three | Level Four | Level Five :: ")
    # cap holds everywhere
    assert all(len(c.heading_path) <= 3 for c in chunks)


def test_determinism():
    a = split_structure_aware(MARKDOWN, DOC)
    b = split_structure_aware(MARKDOWN, DOC)
    assert a == b


def test_split_plain_compat():
    text = "\n\n".join(_para("Plain", 30) for _ in range(4))
    pieces = split_plain(text, chunk_size=500, overlap=60)
    assert pieces and all(isinstance(p, str) for p in pieces)
    assert all(len(p) <= 500 for p in pieces)
    # no contextual prefixes anywhere
    assert all(" :: " not in p for p in pieces)
    # content is preserved (probe sentence survives the split)
    assert any("Plain sentence 0 discusses" in p for p in pieces)
    assert split_plain("", 500, 60) == []
    assert split_plain("tiny", 500, 60) == ["tiny"]
