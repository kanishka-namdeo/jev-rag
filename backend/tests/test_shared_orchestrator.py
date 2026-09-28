"""Tests for the shared-orchestrator bench contract (M5 refactor).

The bench runner no longer hand-mirrors the pipelines: both arms are driven
through ChatService.run(bench=True). These tests pin the contract:

1. _run_arm extracts exactly what the bench records from the event stream
   (files from `sources`, pre_files from `retrieval` — last event wins —
   everything else from `done`).
2. Bench mode adds context_used to the done event and writes NO conversation
   rows (SSE mode still does).
3. Bench mode PROPAGATES exceptions (engine-retry logic depends on it) while
   SSE mode converts them to error events.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="jevrag-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")

from app.db import init_db  # noqa: E402  (env must be set first)

init_db()


# ------------------------------------------------------------------ fixtures

class _StubChat:
    """Scripted ChatService: replays a fixed event stream."""

    def __init__(self, events: list[dict]):
        self.events = events
        self.requests: list = []

    async def run(self, req):
        self.requests.append(req)
        for evt in self.events:
            yield evt


def _make_runner(stub: _StubChat):
    from app.bench.runner import BenchRunner
    from app.bench.scenarios import BenchQuestion

    runner = BenchRunner.__new__(BenchRunner)  # no models / judge needed
    runner.chat = stub
    q = BenchQuestion(
        id="q1", question="What is X?", reference="X is 42", gold_files=["doc-a.md"],
        qtype="single_hop", answerable=True)
    return runner, q


# ------------------------------------------------------------------ _run_arm

def test_run_arm_extracts_from_events():
    events = [
        {"type": "meta", "conversation_id": "c1"},
        {"type": "retrieval", "retrieved": [
            {"filename": "doc-b.md", "rank": 1}, {"filename": "doc-a.md", "rank": 2}]},
        {"type": "sources", "citations": [
            {"filename": "doc-a.md", "index": 1}, {"filename": "doc-c.md", "index": 2}]},
        {"type": "done", "content": "X is 42 [1].", "model": "m", "usage": {"prompt_tokens": 10},
         "timings": {"retrieval_ms": 12.0, "llm_ms": 30.0}, "decisions": [{"name": "rerank"}],
         "context_used": "Passage [1]...", "context_sufficiency": 0.8, "verification": 0.9,
         "latency_ms": 45.0},
    ]
    runner, q = _make_runner(_StubChat(events))
    arm = asyncio.run(runner._run_arm("hybrid", q, ["d1", "d2"]))
    # files come from the LAST sources event (post-screening kept passages)
    assert arm["files"] == ["doc-a.md", "doc-c.md"]
    # pre_files come from the retrieval event (pre-rerank pool)
    assert arm["pre_files"] == ["doc-b.md", "doc-a.md"]
    assert arm["answer"] == "X is 42 [1]." and arm["model"] == "m"
    assert arm["context"] == "Passage [1]..."
    assert arm["sufficiency_p"] == 0.8 and arm["verification_p"] == 0.9
    assert arm["timings"]["latency_ms"] == 45.0
    assert arm["timings"]["llm_ms"] == 30.0
    assert arm["decisions"] == [{"name": "rerank"}]


def test_run_arm_last_retrieval_event_wins():
    """The corrective retry re-emits retrieval — the bench must record the retry pool."""
    events = [
        {"type": "retrieval", "retrieved": [{"filename": "old.md", "rank": 1}]},
        {"type": "retrieval", "retrieved": [{"filename": "new.md", "rank": 1}]},
        {"type": "sources", "citations": []},
        {"type": "done", "content": "ans", "timings": {}, "latency_ms": 1.0},
    ]
    runner, q = _make_runner(_StubChat(events))
    arm = asyncio.run(runner._run_arm("hybrid", q, []))
    assert arm["pre_files"] == ["new.md"]
    assert arm["files"] == []
    assert arm["answer"] == "ans" and arm["sufficiency_p"] is None


def test_run_arm_passes_bench_request():
    events = [{"type": "done", "content": "a", "timings": {}}]
    stub = _StubChat(events)
    runner, q = _make_runner(stub)
    asyncio.run(runner._run_arm("traditional", q, ["d1", "d2"]))
    req = stub.requests[0]
    assert req.bench is True
    assert req.doc_ids == ["d1", "d2"]
    assert req.mode == "traditional"
    assert req.message == "What is X?"


# ------------------------------------------------------------- ChatService bench mode

class _FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _FakeStore:
    def __init__(self, empty: bool = False):
        self.empty = empty
        self.revision = 0

    def get_chunks_by_ids(self, ids):
        return []

    def all_chunks(self, doc_ids=None):
        return []

    def query(self, embedding, k, doc_ids=None):
        from app.rag.retriever import RetrievedChunk
        if self.empty:
            return []
        return [RetrievedChunk(chunk_id="d1:0", text="Paris is the capital of France.",
                               doc_id="d1", filename="doc-a.md", chunk_index=0,
                               similarity=0.91)]

    def count(self) -> int:
        return 0 if self.empty else 1


class _FakeLLM:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def stream_answer(self, model, system, user, history=None):
        from app.llm.dashscope import StreamEvent
        if self.fail:
            raise RuntimeError("boom")
        yield StreamEvent(type="delta", content="Paris [1].")
        yield StreamEvent(type="usage", usage={"prompt_tokens": 5, "completion_tokens": 3,
                                               "_llm_ms": 10.0, "_content": "Paris [1]."})

    def complete(self, model, system, user, **kwargs):
        return "done", {"prompt_tokens": 1}


class _NoJev:
    pass


def _service(llm=None, store=None, **settings_over):
    from app.config import Settings
    from app.rag.pipelines import ChatService
    # hermetic default: no network reranker (cross mode would download the
    # ONNX model); individual tests override to exercise specific modes
    over = {"rerank_mode": "none", **settings_over}
    return ChatService(Settings(_env_file=None, **over), llm or _FakeLLM(), _NoJev(),
                       _FakeEmbedder(), store or _FakeStore())


def _collect(async_gen):
    out = []
    async def drive():
        async for evt in async_gen:
            out.append(evt)
    asyncio.run(drive())
    return out


def test_bench_mode_done_event_carries_context_and_no_db_rows():
    from app.db import Conversation, db_session
    from app.schemas import ChatRequest

    before = 0
    with db_session() as s:
        before = len(s.query(Conversation).all())

    events = _collect(_service().run(
        ChatRequest(message="capital of France?", mode="traditional", bench=True)))
    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert "context_used" in done[0]
    assert "Paris is the capital of France." in done[0]["context_used"]
    assert done[0]["content"] == "Paris [1]."

    with db_session() as s:
        after = len(s.query(Conversation).all())
    assert before == after  # bench mode never writes conversations


def test_sse_mode_has_no_context_used_and_persists():
    from app.db import Conversation, db_session
    from app.schemas import ChatRequest

    events = _collect(_service().run(
        ChatRequest(message="capital of France?", mode="traditional")))
    done = [e for e in events if e["type"] == "done"][0]
    assert "context_used" not in done  # keep the SSE payload lean

    with db_session() as s:
        convs = s.query(Conversation).all()
        assert len(convs) == 1  # SSE mode persists the conversation


def test_bench_mode_propagates_errors():
    from app.schemas import ChatRequest

    try:
        _collect(_service(llm=_FakeLLM(fail=True)).run(
            ChatRequest(message="q", mode="traditional", bench=True)))
        raise AssertionError("expected the exception to propagate")
    except RuntimeError as e:
        assert "boom" in str(e)


def test_sse_mode_converts_errors_to_events():
    from app.schemas import ChatRequest

    events = _collect(_service(llm=_FakeLLM(fail=True)).run(
        ChatRequest(message="q", mode="traditional")))
    assert any(e["type"] == "error" for e in events)
