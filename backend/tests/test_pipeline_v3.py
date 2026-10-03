"""Tests for the v3 hybrid pipeline: gate inversion + hard-path escalation.

Drives ChatService.run(bench=True, mode=hybrid) with a fully faked stack and
pins the v3 contract:
- easy path: gate passes -> NO decompose / battery / best-of-2, one cloud call
- hard path: gate fails -> decompose -> multi-retrieval -> retry loop
- escalate override (never/always/oracle bounders)
- gate_mode jev / none arms
- no_retrieval fast path
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
from app.llm.dashscope import StreamEvent  # noqa: E402
from app.rag.prompts import DECOMPOSE_SYSTEM, QUERY_REWRITE_SYSTEM  # noqa: E402


# ------------------------------------------------------------------ fakes

class FakeJev:
    def __init__(self, effort="single_pass", effort_p=None, sufficiency=0.9):
        self.effort = effort
        self.effort_p = effort_p or {"single_pass": 0.9, "no_retrieval": 0.05,
                                     "multi_step": 0.05}
        self.sufficiency_p = sufficiency
        self.calls = []

    def effort_routing(self, query):
        self.calls.append(("effort", query))
        rec = {"name": "effort", "label": "effort", "kind": "choice",
               "question": "q", "answer": self.effort,
               "probabilities": self.effort_p, "confidence": 0.5,
               "latency_ms": 1.0, "usage": None}
        return self.effort, dict(self.effort_p), 0.5, rec

    def sufficiency(self, query, ctx):
        self.calls.append(("sufficiency", ctx[:40]))
        rec = {"name": "sufficiency", "label": "sufficiency", "kind": "noul",
               "question": "q", "answer": self.sufficiency_p,
               "probabilities": {"true": self.sufficiency_p}, "confidence": None,
               "latency_ms": 1.0, "usage": None}
        return self.sufficiency_p, rec

    def select_best_candidate(self, query, ctx, candidates):
        self.calls.append(("select", list(candidates)))
        rec = {"name": "best_of_2", "label": "best_of_2", "kind": "noul",
               "question": "q", "answer": "direct",
               "probabilities": {"direct": 0.9, "reasoned": 0.3}, "confidence": None,
               "latency_ms": 1.0, "usage": None}
        return "direct", {"direct": 0.9, "reasoned": 0.3}, rec

    def verify_citations_and_quality(self, query, answer, ctx, labeled, cited, cl):
        self.calls.append(("verify", cited))
        verdicts = {n: {"verdict": "supports", "confidence": 0.9} for n in (cited or [1])}
        recs = [{"name": "citations", "label": "citations", "kind": "choice",
                 "question": "q", "answer": "supports", "probabilities": None,
                 "confidence": 0.9, "latency_ms": 1.0, "usage": None}]
        return verdicts, 0.9, 0.8, recs

    def rerank_chunks(self, query, chunks, cl):
        self.calls.append(("jev_rerank", len(chunks)))
        ranked = list(chunks)
        for i, c in enumerate(ranked):
            c["jev_score"] = 0.9 - i * 0.3
        rec = {"name": "rerank", "label": "Jev rerank", "kind": "noul",
               "question": "q", "answer": {}, "probabilities": None,
               "confidence": None, "latency_ms": 1.0, "usage": None}
        return ranked, rec


class FakeLLM:
    def __init__(self):
        self.completes = []

    def stream_answer(self, model, system, user, history=None):
        yield StreamEvent(type="delta", content="streamed answer [1].")
        yield StreamEvent(type="usage", usage={"prompt_tokens": 7, "completion_tokens": 4,
                                               "_llm_ms": 12.0, "_content": "streamed answer [1]."})

    def complete(self, model, system, user, **kw):
        self.completes.append((system[:24], kw.get("enable_thinking")))
        if system == DECOMPOSE_SYSTEM:
            return '["what is alpha part", "what is beta part"]', {"prompt_tokens": 3}
        if system == QUERY_REWRITE_SYSTEM:
            return "alpha beta rewritten", {"prompt_tokens": 3}
        text = "reasoned answer" if kw.get("enable_thinking") else "direct answer"
        return text, {"prompt_tokens": 4}


class StubReranker:
    def __init__(self, scores):
        self.scores = scores

    def load(self):
        return True

    def score_pairs(self, query, passages, batch_size=8):
        return self.scores[: len(passages)] + [0.01] * max(0, len(passages) - len(self.scores))


class FakeEmbedder:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class FakeStore:
    def __init__(self, n=10):
        self.n = n
        self.revision = 0

    def get_chunks_by_ids(self, ids):
        return []

    def all_chunks(self, doc_ids=None):
        return []

    def count(self):
        return self.n

    def query(self, embedding, k, doc_ids=None):
        from app.rag.retriever import RetrievedChunk
        return [RetrievedChunk(chunk_id=f"d:{i}", text=f"passage {i} about the topic",
                               doc_id="d", filename="d.md", chunk_index=i,
                               similarity=0.9 - i * 0.05)
                for i in range(min(k, self.n))]


def _service(rerank_scores, jev=None, **over):
    from app.rag.pipelines import ChatService
    s = Settings(_env_file=None, **over)
    chat = ChatService(s, FakeLLM(), jev or FakeJev(), FakeEmbedder(), FakeStore())
    chat.reranker = StubReranker(rerank_scores)
    return chat


def _run(chat, message="what is the answer", escalate=None):
    from app.schemas import ChatRequest
    out = []
    async def drive():
        async for evt in chat.run(ChatRequest(message=message, mode="hybrid",
                                              bench=True, escalate=escalate)):
            out.append(evt)
    asyncio.run(drive())
    return out


def _done(events):
    return [e for e in events if e["type"] == "done"][0]


# ------------------------------------------------------------------ easy path

def test_easy_path_when_gate_passes():
    chat = _service([0.97])  # top-1 relevance high -> gate passes
    events = _run(chat)
    done = _done(events)
    assert done.get("path") == "easy"
    names = [d["name"] for d in done["decisions"]]
    assert "gate" in names and "decompose" not in names
    # no best-of-2, single streamed answer
    assert done.get("best_of") is None
    assert done["content"] == "streamed answer [1]."
    assert done["context_sufficiency"] == 0.97  # gate p = top-1 score
    gate = [d for d in done["decisions"] if d["name"] == "gate"][0]
    assert gate["mode"] == "features" and gate["answer"] == "easy"


def test_hard_path_when_gate_fails():
    chat = _service([0.2])  # low relevance -> escalate
    events = _run(chat)
    done = _done(events)
    assert done.get("path") == "hard"
    names = [d["name"] for d in done["decisions"]]
    assert "gate" in names and "decompose" in names and "best_of_2" in names
    assert "corrective" in names  # gate still failing after retry -> rewrite
    assert done["content"] in ("direct answer", "reasoned answer")
    assert done.get("retried") is True


# ------------------------------------------------------------------ bounders

def test_escalate_override_forces_easy_path():
    chat = _service([0.05])  # scores scream escalate...
    events = _run(chat, escalate=False)  # ...but the bounder forces easy
    done = _done(events)
    assert done.get("path") == "easy"
    assert done["content"] == "streamed answer [1]."
    names = [d["name"] for d in done["decisions"]]
    assert "decompose" not in names
    gate = [d for d in done["decisions"] if d["name"] == "gate"][0]
    assert gate["mode"] == "injected"


def test_escalate_override_forces_hard_path():
    chat = _service([0.99])
    events = _run(chat, escalate=True)
    done = _done(events)
    assert done.get("path") == "hard"
    assert "decompose" in [d["name"] for d in done["decisions"]]


# ------------------------------------------------------------------ gate arms

def test_gate_mode_jev_uses_sufficiency_noul():
    jev = FakeJev(sufficiency=0.9)
    chat = _service([0.05], jev=jev, gate_mode="jev")
    events = _run(chat)
    done = _done(events)
    assert ("sufficiency",) not in [] and any(c[0] == "sufficiency" for c in jev.calls)
    assert done.get("path") == "easy"  # 0.9 >= 0.5 threshold
    gate = [d for d in done["decisions"] if d["name"] == "gate"][0]
    assert gate["mode"] == "jev"


def test_gate_mode_jev_escalates_when_insufficient():
    jev = FakeJev(sufficiency=0.2)
    chat = _service([0.97], jev=jev, gate_mode="jev")
    events = _run(chat)
    done = _done(events)
    assert done.get("path") == "hard"


def test_gate_mode_none_never_escalates():
    chat = _service([0.05], gate_mode="none")
    events = _run(chat)
    done = _done(events)
    assert done.get("path") == "easy"
    gate = [d for d in done["decisions"] if d["name"] == "gate"][0]
    assert gate["mode"] == "none"


def test_gate_threshold_is_a_knob():
    chat = _service([0.6], gate_score_threshold=0.8)  # 0.6 < 0.8 -> escalate
    events = _run(chat)
    assert _done(events).get("path") == "hard"


# ------------------------------------------------------------------ fast path

def test_no_retrieval_fast_path():
    jev = FakeJev(effort="no_retrieval",
                  effort_p={"no_retrieval": 0.95, "single_pass": 0.03, "multi_step": 0.02})
    chat = _service([0.9], jev=jev)
    events = _run(chat, message="hello, how are you?")
    done = _done(events)
    assert done.get("effort") == "no_retrieval"
    assert done["content"] == "streamed answer [1]."
    assert done["retrieved"] == []
    assert "context_used" in done  # bench mode always carries the context


# ------------------------------------------------------------------ concurrency

def test_effort_routing_and_retrieval_overlap():
    """Effort routing runs concurrently with first retrieval (no serial stall).

    Timings: route branch = count(0.4) + jev routing(0.4) = 0.8s serial inside
    its branch; retrieve branch = count(0.4) + fast retrieval. Fully serial
    execution would be ~1.2s (count + route + count + retrieve); the concurrent
    gather finishes in ~0.8s (max branch).
    """
    import time as _t
    from app.rag.pipelines import ChatService

    class SlowJev(FakeJev):
        def effort_routing(self, query):
            _t.sleep(0.4)
            return super().effort_routing(query)

    class SlowStore(FakeStore):
        def count(self):
            _t.sleep(0.4)
            return self.n

    s = Settings(_env_file=None)
    chat = ChatService(s, FakeLLM(), SlowJev(), FakeEmbedder(), SlowStore())
    chat.reranker = StubReranker([0.97])
    t0 = _t.perf_counter()
    _run(chat)
    elapsed = _t.perf_counter() - t0
    # serial floor: 0.4+0.4+0.4 = 1.2s; concurrent max-branch: ~0.8s
    assert elapsed < 1.0, f"routing did not overlap retrieval (took {elapsed:.2f}s)"


# ------------------------------------------------------------------ recording honesty

def test_sum_token_usage_adds_decision_usages():
    from app.rag.pipelines import sum_token_usage

    usage = {"prompt_tokens": 7, "completion_tokens": 4}
    decisions = [
        {"name": "decompose", "usage": {"prompt_tokens": 3, "completion_tokens": 12}},
        {"name": "gate", "usage": None},
        {"name": "corrective", "usage": {"prompt_tokens": 5}},  # partial shape
    ]
    assert sum_token_usage(usage, decisions) == {"prompt_tokens": 15, "completion_tokens": 16}
    assert sum_token_usage(None, None) == {"prompt_tokens": 0, "completion_tokens": 0}
    assert sum_token_usage(usage, []) == {"prompt_tokens": 7, "completion_tokens": 4}


def test_no_verify_arm_is_generation_identical_to_base():
    """H-VERIFY is a post-answer observation arm: with verification disabled the
    generation path must be byte-identical to base (same seed/fakes). A null
    accuracy delta on this arm is therefore STRUCTURAL, not a finding about
    citation verification helping or hurting — it can only move cost/latency and
    the trustworthiness of the [n] labels."""
    easy = _service([0.97])  # easy path: verification is the only jev call
    base_done = _done(_run(easy))
    no_verify = _service([0.97], hybrid_verify_answers=False)
    nv_done = _done(_run(no_verify))
    assert nv_done["content"] == base_done["content"]
    assert [d["name"] for d in nv_done["decisions"]] == ["effort", "rerank", "gate"]
    assert nv_done.get("verification") is None and nv_done.get("quality_score") is None


def test_bench_done_carries_per_chunk_contexts():
    easy = _service([0.97])
    done = _done(_run(easy))
    chunks = done.get("context_chunks")
    assert isinstance(chunks, list) and len(chunks) == 4  # top_k_use default
    assert all("passage" in c for c in chunks)
    # the formatted block the judge sees covers the same passages, in order
    for c in chunks:
        assert c[:40] in done["context_used"]


def test_rerank_uses_own_char_limit_not_jev_knob():
    """The cross-encoder must not be throttled by jev_rerank_char_limit (a jev
    decision-latency knob). rerank_char_limit=0 (default) scores full chunks."""
    seen = {}

    class RecordingReranker(StubReranker):
        def score_pairs(self, query, passages, batch_size=8):
            seen["widths"] = sorted({len(p) for p in passages})
            return super().score_pairs(query, passages, batch_size)

    from app.rag.pipelines import ChatService
    s = Settings(_env_file=None, jev_rerank_char_limit=10)  # hostile jev knob
    assert s.rerank_char_limit == 0  # default: full chunk
    chat = ChatService(s, FakeLLM(), FakeJev(), FakeEmbedder(), FakeStore())
    chat.reranker = RecordingReranker([0.97])
    _run(chat)
    assert seen["widths"] == [len("passage 9 about the topic")]  # untruncated

    chat2 = ChatService(Settings(_env_file=None, rerank_char_limit=10),
                        FakeLLM(), FakeJev(), FakeEmbedder(), FakeStore())
    chat2.reranker = RecordingReranker([0.97])
    _run(chat2)
    # explicit limit still truncates (opt-in narrowing, not a shared default)
    assert seen["widths"] == [10]
