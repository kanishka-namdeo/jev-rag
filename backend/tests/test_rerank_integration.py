"""Tests for the v3 rerank slot (M4): cross | jev | none dispatch, fallback,
and the upgraded traditional (2026-baseline) flow.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="jevrag-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")

from app.config import Settings  # noqa: E402


# ------------------------------------------------------------------ stubs

class _StubReranker:
    """Stand-in for CrossEncoderReranker — no network, scripted scores."""

    def __init__(self, scores=None, fail=False):
        self.scores = scores
        self.fail = fail
        self.loaded = False

    def load(self) -> bool:
        self.loaded = not self.fail
        return self.loaded

    def score_pairs(self, query, passages, batch_size=8):
        if self.fail:
            return None
        return self.scores[: len(passages)] if self.scores else [0.5] * len(passages)


class _StubJev:
    def __init__(self):
        self.calls = []

    def rerank_chunks(self, query, chunks, char_limit):
        self.calls.append((query, chunks, char_limit))
        # deterministic: reverse order, uniform scores
        ranked = list(reversed(chunks))
        for i, c in enumerate(ranked):
            c["jev_score"] = 0.9 - i * 0.1
        rec = {"name": "rerank", "label": "Jev rerank (calibrated relevance per passage)",
               "kind": "noul", "question": "q", "answer": {}, "probabilities": None,
               "confidence": None, "latency_ms": 5.0, "usage": None}
        return ranked, rec


class _FakeEmbedder:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class _FakeStore:
    def __init__(self):
        self.revision = 0

    def get_chunks_by_ids(self, ids):
        return []

    def all_chunks(self, doc_ids=None):
        return []

    def count(self):
        return 3

    def query(self, embedding, k, doc_ids=None):
        from app.rag.retriever import RetrievedChunk
        texts = ["alpha passage", "beta passage", "gamma passage"]
        return [RetrievedChunk(chunk_id=f"d:{i}", text=t, doc_id="d", filename="d.md",
                               chunk_index=i, similarity=0.9 - i * 0.1)
                for i, t in enumerate(texts)]


class _FakeLLM:
    def stream_answer(self, model, system, user, history=None):
        from app.llm.dashscope import StreamEvent
        yield StreamEvent(type="delta", content="ok")
        yield StreamEvent(type="usage", usage={"prompt_tokens": 5, "completion_tokens": 2,
                                               "_llm_ms": 10.0, "_content": "ok"})

    def complete(self, model, system, user, **kw):
        return "done", {"prompt_tokens": 1}


def _service(rerank_mode="cross", reranker=None, jev=None, **over):
    from app.rag.pipelines import ChatService
    s = Settings(_env_file=None, rerank_mode=rerank_mode, **over)
    chat = ChatService(s, _FakeLLM(), jev or _StubJev(), _FakeEmbedder(), _FakeStore())
    if reranker is not None:
        chat.reranker = reranker
    return chat


def _pool(chat):
    out, _ms = chat._retrieve("query", 10)
    for i, c in enumerate(out):
        c["retrieval_rank"] = i + 1
        c["index"] = i + 1
    return out


# ------------------------------------------------------------------ _rerank dispatch

def test_cross_mode_orders_by_score_and_sets_fields():
    chat = _service(reranker=_StubReranker(scores=[0.1, 0.9, 0.5]))
    pool = _pool(chat)
    ranked, rec = chat._rerank("query", pool)
    assert [c["text"] for c in ranked] == ["beta passage", "gamma passage", "alpha passage"]
    assert ranked[0]["jev_score"] == 0.9 and ranked[0]["ce_score"] == 0.9
    assert rec["engine"] == "cross-encoder" and rec["kind"] == "score"
    assert rec["probabilities"]["[2]"] == 0.9  # beta was index 2 in the pool
    assert rec["latency_ms"] >= 0


def test_cross_mode_falls_back_to_jev_when_load_fails():
    jev = _StubJev()
    chat = _service(reranker=_StubReranker(fail=True), jev=jev)
    pool = _pool(chat)
    ranked, rec = chat._rerank("query", pool)
    assert jev.calls, "fallback must invoke the jev rerank"
    assert "FALLBACK" in rec["label"]
    assert [c["text"] for c in ranked] == ["gamma passage", "beta passage", "alpha passage"]


def test_jev_mode_dispatches_to_engine():
    jev = _StubJev()
    chat = _service(rerank_mode="jev", jev=jev)
    pool = _pool(chat)
    chat._rerank("query", pool)
    assert len(jev.calls) == 1
    q, chunks, cl = jev.calls[0]
    assert q == "query" and len(chunks) == 3
    assert cl == Settings(_env_file=None).jev_rerank_char_limit


def test_none_mode_passthrough():
    chat = _service(rerank_mode="none")
    pool = _pool(chat)
    ranked, rec = chat._rerank("query", pool)
    assert [c["text"] for c in ranked] == [c["text"] for c in pool]
    assert rec["engine"] == "none"


def test_cross_mode_falls_back_on_score_length_mismatch():
    jev = _StubJev()
    chat = _service(reranker=_StubReranker(scores=[0.9, 0.1]), jev=jev)  # 2 scores, 3 chunks
    pool = _pool(chat)
    ranked, rec = chat._rerank("query", pool)
    assert jev.calls and "FALLBACK" in rec["label"]


# ------------------------------------------------------------------ traditional v3 flow

def _collect(async_gen):
    out = []
    async def drive():
        async for evt in async_gen:
            out.append(evt)
    asyncio.run(drive())
    return out


def test_traditional_v3_reranks_and_emits_events():
    from app.schemas import ChatRequest
    chat = _service(reranker=_StubReranker(scores=[0.2, 0.95, 0.4]))
    events = _collect(chat.run(ChatRequest(message="q", mode="traditional", bench=True)))
    types = [e["type"] for e in events]
    assert "retrieval" in types and "rerank" in types
    rerank_evt = [e for e in events if e["type"] == "rerank"][0]
    assert rerank_evt["kept"][0]["snippet"].startswith("beta")
    dec = [e for e in events if e["type"] == "decision"][0]["decision"]
    assert dec["engine"] == "cross-encoder"
    sources = [e for e in events if e["type"] == "sources"][0]["citations"]
    assert sources[0]["rerank_score"] == 0.95
    done = [e for e in events if e["type"] == "done"][0]
    assert "rerank_ms" in done["timings"]


def test_traditional_none_mode_keeps_retrieval_order():
    from app.schemas import ChatRequest
    chat = _service(rerank_mode="none")
    events = _collect(chat.run(ChatRequest(message="q", mode="traditional", bench=True)))
    rerank_evt = [e for e in events if e["type"] == "rerank"][0]
    assert rerank_evt["kept"][0]["snippet"].startswith("alpha")
