"""Tests for the ONNX cross-encoder reranker (app.rag.crossenc).

Live tests download ~91 MB from the HuggingFace CDN on the FIRST run only
(7 s measured in the sandbox; HF disk cache afterwards). Set
JEVRAG_SKIP_NET_TESTS=1 to skip everything that touches the network — the
hermetic contract test still runs.

Run: cd backend && .venv/bin/python -m pytest tests/test_crossenc.py -v
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

import pytest

from app.rag.crossenc import CrossEncoderReranker

_SKIP_NET = os.environ.get("JEVRAG_SKIP_NET_TESTS", "") == "1"

QUERY = "What is the capital of France?"
RELEVANT = "Paris is the capital and largest city of France."
RELEVANT_ALT = "Paris is the capital of France."
IRRELEVANT = "The sky is blue on clear days."


# -- hermetic (no network) -------------------------------------------------


def test_not_loaded_contract():
    """A fresh instance is inert: None for real scoring, [] for degenerate
    input, rerank passes chunks through unmodified, info reports not-loaded."""
    r = CrossEncoderReranker()  # lazy: construction touches no network
    assert r.score_pairs("q", ["some passage"]) is None
    assert r.score_pairs("q", []) == []  # empty short-circuits, even unloaded
    chunks = [{"text": IRRELEVANT, "id": "a"}, {"text": RELEVANT, "id": "b"}]
    out = r.rerank(QUERY, chunks)
    assert out == chunks  # graceful passthrough, original order, no ce_score
    assert all("ce_score" not in c for c in out)
    assert r.rerank(QUERY, []) == []
    info = r.info()
    assert info == {
        "ok": False,
        "model": "Xenova/ms-marco-MiniLM-L-6-v2",
        "backend": "onnxruntime CPU",
        "loaded": False,
    }
    assert r.load.__doc__  # load() is documented (never-raises contract)


# -- live (download on first run) -------------------------------------------


@pytest.mark.skipif(_SKIP_NET, reason="JEVRAG_SKIP_NET_TESTS=1")
def test_score_pairs_relevant_above_irrelevant():
    r = CrossEncoderReranker()
    assert r.load() is True
    scores = r.score_pairs(QUERY, [RELEVANT, IRRELEVANT, RELEVANT_ALT])
    assert scores is not None and len(scores) == 3
    assert all(0.0 <= s <= 1.0 for s in scores)
    # relevant clearly above irrelevant (measured: ~1.0 vs ~0.0000)
    assert scores[0] > scores[1]
    assert scores[0] - scores[1] > 0.2
    # both relevant passages score close to each other
    assert abs(scores[0] - scores[2]) < 0.15


@pytest.mark.skipif(_SKIP_NET, reason="JEVRAG_SKIP_NET_TESTS=1")
def test_rerank_orders_and_annotates():
    r = CrossEncoderReranker()
    assert r.load() is True
    chunks = [
        {"text": "The mitochondria is the powerhouse of the cell.", "id": "a"},
        {"text": RELEVANT_ALT, "id": "b"},
    ]
    out = r.rerank(QUERY, chunks)
    assert len(out) == 2
    assert out[0]["id"] == "b"  # relevant passage ranked first
    assert isinstance(out[0]["ce_score"], float)
    assert 0.0 <= out[0]["ce_score"] <= 1.0
    assert out[0]["ce_score"] >= out[1]["ce_score"]
    assert "ce_score" in out[1]
    # originals are never mutated (rerank returns dict copies)
    assert all("ce_score" not in c for c in chunks)
    assert chunks[0]["id"] == "a"
    # empty input
    assert r.rerank(QUERY, []) == []


@pytest.mark.skipif(_SKIP_NET, reason="JEVRAG_SKIP_NET_TESTS=1")
def test_load_idempotent():
    r = CrossEncoderReranker()
    assert r.load() is True
    session_before = r._session
    t0 = time.perf_counter()
    assert r.load() is True  # cached: fast, no re-download
    assert time.perf_counter() - t0 < 1.0
    assert r._session is session_before  # same InferenceSession object
    assert r.info()["loaded"] is True and r.info()["ok"] is True
    assert "error" not in r.info()


@pytest.mark.skipif(_SKIP_NET, reason="JEVRAG_SKIP_NET_TESTS=1")
def test_bogus_model_fails_gracefully():
    """A nonexistent repo must produce a graceful False — never an exception —
    within a bounded time; the error surfaces via info()."""
    r = CrossEncoderReranker(model_name="Xenova/nonexistent-model-xyz")
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(r.load)
        try:
            ok = future.result(timeout=120)
        except FuturesTimeoutError:
            pytest.fail("load() on bogus model did not fail within 120 s")
        except Exception as e:  # pragma: no cover — contract violation
            pytest.fail(f"load() raised {type(e).__name__}: {e}")
    finally:
        executor.shutdown(wait=False)
    assert ok is False
    assert r.score_pairs("q", ["p"]) is None  # not loaded -> None
    info = r.info()
    assert info["ok"] is False and info["loaded"] is False
    assert info["model"] == "Xenova/nonexistent-model-xyz"
    assert "error" in info and isinstance(info["error"], str) and info["error"]
    assert r.load() is False  # sticky failure, still no exception


@pytest.mark.skipif(_SKIP_NET, reason="JEVRAG_SKIP_NET_TESTS=1")
def test_batching_preserves_order():
    """10 passages scored with batch_size=3: exactly 10 scores, order intact
    (planted relevant passage is the argmax at its original index), and
    scores are independent of the batch split."""
    r = CrossEncoderReranker()
    assert r.load() is True
    passages = [f"Generic filler passage number {i} about other topics." for i in range(10)]
    passages[7] = RELEVANT_ALT  # relevant item lands mid-batch (3rd batch)
    scores = r.score_pairs(QUERY, passages, batch_size=3)
    assert scores is not None and len(scores) == 10
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores.index(max(scores)) == 7
    # batch size must not change any score
    scores_whole = r.score_pairs(QUERY, passages, batch_size=10)
    assert scores == pytest.approx(scores_whole)
