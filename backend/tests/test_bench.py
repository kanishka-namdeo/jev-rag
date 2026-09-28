"""Benchmark subsystem tests — hermetic (no models loaded, no network).

Run: cd backend && .venv/bin/python -m pytest tests -v
"""
from __future__ import annotations

import os
import tempfile

# Make tests hermetic BEFORE importing app code (same pattern as test_basic.py).
_TMP = tempfile.mkdtemp(prefix="jevrag-bench-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")


# ================================================================ metrics
def test_retrieval_metrics_perfect():
    from app.bench.metrics import retrieval_metrics

    m = retrieval_metrics(["a.md", "b.md", "c.md"], ["a.md"])
    assert m["hit1"] == 1 and m["hit4"] == 1 and m["hit10"] == 1
    assert m["mrr"] == 1.0
    assert m["recall4"] == 1.0 and m["ndcg10"] == 1.0


def test_retrieval_metrics_rank_3():
    from app.bench.metrics import retrieval_metrics

    m = retrieval_metrics(["x.md", "y.md", "a.md", "z.md"], ["a.md"])
    assert m["hit1"] == 0 and m["hit4"] == 1
    assert m["mrr"] == round(1 / 3, 4)


def test_retrieval_metrics_multihop_recall():
    from app.bench.metrics import retrieval_metrics

    # two gold files; b.md only appears at rank 5 (outside top-4)
    m = retrieval_metrics(["a.md", "a.md", "z.md", "z.md", "b.md", "x.md"],
                          ["a.md", "b.md"])
    assert m["recall4"] == 0.5
    assert m["recall10"] == 1.0
    assert m["hit4"] == 1 and m["hit1"] == 1
    # file-level dedup: rels = [1,0,0,0,1,0]; DCG = 1 + 1/log2(6); IDCG (2 gold) = 1 + 1/log2(3)
    import math
    dcg = 1 + 1 / math.log2(6)
    idcg = 1 + 1 / math.log2(3)
    assert m["ndcg10"] == round(dcg / idcg, 4)


def test_retrieval_metrics_duplicate_gold_chunks_do_not_inflate_ndcg():
    import math

    from app.bench.metrics import retrieval_metrics

    # two chunks of the SAME gold file in the top ranks: file-level relevance
    m = retrieval_metrics(["a.md", "a.md", "x.md"], ["a.md"])
    assert m["ndcg10"] == 1.0            # deduped: file counts once, at rank 1
    m2 = retrieval_metrics(["a.md", "a.md", "b.md", "x.md"], ["a.md", "b.md"])
    # b.md's first occurrence lands at rank 3 (duplicate a.md occupies rank 2)
    assert m2["ndcg10"] == round((1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3)), 4)
    assert m2["recall4"] == 1.0
    # gold file at rank 2 with a duplicate right after must stay < 1
    m3 = retrieval_metrics(["x.md", "a.md", "a.md"], ["a.md"])
    assert m3["ndcg10"] < 1.0 and m3["hit4"] == 1 and m3["mrr"] == 0.5


def test_retrieval_metrics_miss():
    from app.bench.metrics import retrieval_metrics

    m = retrieval_metrics(["x.md", "y.md"], ["a.md"])
    assert m["hit4"] == 0 and m["mrr"] == 0.0 and m["recall4"] == 0.0
    assert m["ndcg10"] == 0.0


def test_agg_retrieval_skips_empty():
    from app.bench.metrics import agg_retrieval

    out = agg_retrieval([{"hit4": 1, "mrr": 1.0}, {}, {"hit4": 0, "mrr": 0.5}])
    assert out["hit4"] == 0.5
    assert out["mrr"] == round((1.0 + 0.5) / 2, 4)


def test_brier():
    from app.bench.metrics import brier

    # perfectly calibrated: p=[1,0], outcomes=[True,False]
    assert brier([1.0, 0.0], [True, False]) == 0.0
    # perfectly wrong
    assert brier([0.0, 1.0], [True, False]) == 1.0


# ================================================================ scenarios
def test_scenario_integrity():
    from app.bench.scenarios import INTERNAL_SCENARIOS, PUBLIC_SCENARIOS, SCENARIOS, doc_path

    ids = set()
    for s in SCENARIOS:
        assert s.id not in ids
        ids.add(s.id)
        assert s.questions, f"scenario {s.id} has no questions"
        assert len(s.docs) >= 3
        # internal corpora are hand-authored (dense, >500B); public benchmark
        # corpora contain verbatim Wikipedia articles — legitimate short stubs —
        # so they only get a near-empty floor.
        min_bytes = 500 if s in INTERNAL_SCENARIOS else 80
        for doc in s.docs:
            p = doc_path(s.id, doc)
            assert p.exists(), f"missing corpus file {p}"
            assert p.stat().st_size > min_bytes, f"corpus file too small: {p}"
        qids = set()
        for q in s.questions:
            assert q.id not in qids
            qids.add(q.id)
            assert q.question.strip()
            if q.answerable:
                assert q.gold_files, f"{s.id}/{q.id}: answerable needs gold files"
                assert q.reference.strip(), f"{s.id}/{q.id}: answerable needs a reference"
                assert set(q.gold_files) <= set(s.docs), \
                    f"{s.id}/{q.id}: gold file not in scenario docs"
            else:
                assert not q.gold_files, f"{s.id}/{q.id}: unanswerable must have no gold"


def test_scenario_coverage():
    from app.bench.scenarios import INTERNAL_SCENARIOS, PUBLIC_SCENARIOS, SCENARIOS

    # internal suite is fixed at 6; public benchmarks (when the manifest was built)
    # append on top — assert both facts explicitly so regressions in either stand out.
    assert len(INTERNAL_SCENARIOS) == 6
    assert len(SCENARIOS) == 6 + len(PUBLIC_SCENARIOS)
    total = sum(len(s.questions) for s in SCENARIOS)
    internal_total = sum(len(s.questions) for s in INTERNAL_SCENARIOS)
    assert internal_total == 48
    assert total == 48 + sum(len(s.questions) for s in PUBLIC_SCENARIOS)
    oos = next(s for s in SCENARIOS if s.id == "outofscope")
    assert oos.question_count(False) == 5 and oos.question_count(True) == 3
    multi = next(s for s in SCENARIOS if s.id == "multilingual")
    assert multi.question_count() == 8
    assert all(q.answerable for q in multi.questions)
    assert any(q.qtype == "cross-lingual" for q in multi.questions)


# ================================================================ judge parsing
def test_absolute_parses_plain_json():
    import types

    from app.bench.judge import BenchJudge

    payload = '{"correctness": 0.9, "faithfulness": 1.0, "abstention": "answered", "reason": "ok"}'
    judge = BenchJudge.__new__(BenchJudge)
    judge.model = "fake"
    judge.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **kw: types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=payload))]))))

    out = judge.absolute("q", "ref", "ctx", "answer")
    assert out["correctness"] == 0.9
    assert out["faithfulness"] == 1.0
    assert out["abstention"] == "answered"
    assert out["reason"] == "ok"


def test_absolute_parses_fenced_json_and_clamps():
    import types

    from app.bench.judge import BenchJudge

    payload = '```json\n{"correctness": 1.7, "faithfulness": -0.2, "abstention": "weird", "reason": "x"}\n```'
    judge = BenchJudge.__new__(BenchJudge)
    judge.model = "fake"
    judge.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **kw: types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=payload))]))))

    out = judge.absolute("q", "ref", "ctx", "answer")
    assert out["correctness"] == 1.0      # clamped
    assert out["faithfulness"] == 0.0     # clamped
    assert out["abstention"] == "answered"  # unknown label -> default


def test_absolute_degrades_on_failure():
    import types

    from app.bench.judge import BenchJudge

    def boom(**kw):
        raise RuntimeError("network down")

    judge = BenchJudge.__new__(BenchJudge)
    judge.model = "fake"
    judge.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=boom)))

    out = judge.absolute("q", "ref", "ctx", "answer")
    assert out["judge_error"] is True
    assert out["correctness"] is None


def test_pairwise_position_swap():
    import types

    from app.bench.judge import BenchJudge

    # order1: A=trad,B=hyb -> "B" (hybrid); order2: A=hyb,B=trad -> "A" (hybrid)
    payloads = ['{"winner": "B", "reason": "b"}', '{"winner": "A", "reason": "a"}']
    judge = BenchJudge.__new__(BenchJudge)
    judge.model = "fake"
    judge.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **kw: types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content=payloads.pop(0)))]))))

    out = judge.pairwise("q", "ref", {"context": "c1", "answer": "a1"},
                         {"context": "c2", "answer": "a2"})
    assert out["winner"] == "hybrid"
    assert out["position_consistent"] is True


def test_pairwise_inconsistent_resolves_to_tie():
    import types

    from app.bench.judge import BenchJudge

    # order1: hybrid better; order2 (swapped): traditional better -> inconsistent
    payloads = ['{"winner": "B", "reason": "b"}', '{"winner": "B", "reason": "b"}']
    judge = BenchJudge.__new__(BenchJudge)
    judge.model = "fake"
    judge.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **kw: types.SimpleNamespace(
                choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content=payloads.pop(0)))]))))

    out = judge.pairwise("q", "ref", {"context": "c1", "answer": "a1"},
                         {"context": "c2", "answer": "a2"})
    assert out["winner"] == "tie"
    assert out["position_consistent"] is False


# ================================================================ bench routes smoke
def test_bench_scenarios_route():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/api/bench/scenarios")
        assert resp.status_code == 200
        body = resp.json()
        # internal suite is always present; public benchmarks appear when the
        # manifest was built in this checkout.
        from app.bench.scenarios import INTERNAL_SCENARIOS, PUBLIC_SCENARIOS
        assert len(body["scenarios"]) == len(INTERNAL_SCENARIOS) + len(PUBLIC_SCENARIOS)
        assert {s["id"] for s in body["scenarios"]} >= {s.id for s in INTERNAL_SCENARIOS}
        for s in body["scenarios"]:
            for key in ("id", "name", "category", "doc_count", "question_count",
                        "answerable", "unanswerable"):
                assert key in s


def test_bench_runs_route_list():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/api/bench/runs")
        assert resp.status_code == 200
        assert "runs" in resp.json()


def test_bench_run_validation():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        resp = client.post("/api/bench/runs", json={"scenario_ids": ["nope"]})
        assert resp.status_code == 400


# ================================================================ jev engine recovery
def test_jev_engine_recovers_after_subprocess_death():
    """OOM resilience: a dead jev-score subprocess (BrokenPipeError) triggers an
    engine reload + single retry instead of poisoning every later call."""
    import sys
    import types

    from app.config import Settings
    from app.llm.jev_engine import JevEngine

    calls = {"n": 0}

    class FakeJevStyle:
        def __init__(self, **kwargs):
            calls["n"] += 1

        def decide(self, state, questions):
            # first instance's decide works once, then dies like a killed subprocess
            if calls["n"] == 1 and calls.get("decided", 0) >= 1:
                raise BrokenPipeError(32, "Broken pipe")
            calls["decided"] = calls.get("decided", 0) + 1
            return {"answers": {"k": {"noul": 0.5}}, "usage": {}}

    fake_module = types.ModuleType("jev_style")
    fake_module.JevStyle = FakeJevStyle
    sys.modules["jev_style"] = fake_module
    try:
        settings = Settings(JEVRAG_LAZY_MODELS="1", JEVRAG_DATA_DIR=_TMP,
                            JEVRAG_DASHSCOPE_API_KEY="test-key")
        engine = JevEngine(settings)
        assert engine.load() is True

        # first call: fine
        out = engine._decide("state", {"k": {"type": "noul", "instructions": "x"}})
        assert out["answers"]["k"]["noul"] == 0.5

        # second call: subprocess died -> automatic reload + retry succeeds
        out2 = engine._decide("state", {"k": {"type": "noul", "instructions": "x"}})
        assert out2["answers"]["k"]["noul"] == 0.5
        assert calls["n"] == 2  # a second subprocess was spawned
    finally:
        sys.modules.pop("jev_style", None)


def test_jev_engine_unavailable_when_reload_fails():
    import sys
    import types

    from app.config import Settings
    from app.llm.jev_engine import JevEngine, JevEngineUnavailable

    class DeadAfterWarmup:
        """Warmup (first decide) succeeds; every later decide dies."""

        def __init__(self, **kwargs):
            self.calls = 0

        def decide(self, state, questions):
            self.calls += 1
            if self.calls > 1:
                raise BrokenPipeError(32, "Broken pipe")
            return {"answers": {}, "usage": {}}

    fake_module = types.ModuleType("jev_style")
    fake_module.JevStyle = DeadAfterWarmup
    sys.modules["jev_style"] = fake_module
    try:
        settings = Settings(JEVRAG_LAZY_MODELS="1", JEVRAG_DATA_DIR=_TMP,
                            JEVRAG_DASHSCOPE_API_KEY="test-key")
        engine = JevEngine(settings)
        assert engine.load() is True  # warmup succeeds
        try:
            engine._decide("state", {"k": {"type": "noul", "instructions": "x"}})
            raise AssertionError("expected JevEngineUnavailable")
        except JevEngineUnavailable:
            pass  # reload spawned a fresh engine, its decide died too -> clean error
    finally:
        sys.modules.pop("jev_style", None)
