"""Lightweight tests that need no models and no network.

Run: cd backend && .venv/bin/python -m pytest tests -v
"""
from __future__ import annotations

import os
import tempfile

# Make tests hermetic BEFORE importing app code: lazy models, temp data dir.
_TMP = tempfile.mkdtemp(prefix="jevrag-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")


def test_health():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_status_shape():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        resp = client.get("/api/system/status")
        assert resp.status_code == 200
        body = resp.json()
        for key in ("dashscope", "jev", "embeddings", "vector_store", "documents"):
            assert key in body


def test_cost_estimation():
    from app.llm.dashscope import estimate_cost_usd

    # qwen3.7-plus: $0.32/M input, $1.28/M output
    cost = estimate_cost_usd("qwen3.7-plus", 1_000_000, 1_000_000)
    assert abs(cost - (0.32 + 1.28)) < 1e-9
    cost2 = estimate_cost_usd("qwen3.7-plus", 1_000, 500)
    assert abs(cost2 - (0.00032 + 0.00064)) < 1e-9
    assert estimate_cost_usd("unknown-model", 100, 100) is None


def test_chat_request_validation():
    from pydantic import ValidationError

    from app.schemas import ChatRequest

    ok = ChatRequest(message="hello", mode="hybrid")
    assert ok.mode == "hybrid"
    try:
        ChatRequest(message="", mode="hybrid")
        raise AssertionError("empty message must fail")
    except ValidationError:
        pass
    try:
        ChatRequest(message="hi", mode="bogus")  # type: ignore[arg-type]
        raise AssertionError("bad mode must fail")
    except ValidationError:
        pass


def test_snippet_and_context():
    from app.rag.pipelines import _snippet
    from app.rag.prompts import format_context

    assert _snippet("a" * 500, n=240).endswith("…")
    assert len(_snippet("short text")) == len("short text")

    ctx = format_context([
        {"chunk_index_label": 1, "filename": "doc.pdf", "text": "first passage"},
        {"chunk_index_label": 2, "filename": "doc.pdf", "text": "second passage"},
    ])
    assert "Passage [1] (source: doc.pdf)" in ctx
    assert "second passage" in ctx
