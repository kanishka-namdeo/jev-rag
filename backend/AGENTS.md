# Backend DOX

## Purpose

- Own the Python FastAPI service: two RAG pipelines (traditional, hybrid), the local Jev-style
  decision engine (System One), ingestion, embeddings/vector store, SQLite persistence, and the
  SSE chat protocol consumed by the frontend.

## Ownership

- `app/main.py` — app factory, lifespan (model warm-up), router mounting (`/api/*` and `/backend-api/*`)
- `app/config.py` — all settings (env prefix `JEVRAG_`, `backend/.env`), LLM price table
- `app/db.py` — SQLAlchemy models: Document, Conversation, Message (+trace JSON)
- `app/schemas.py` — pydantic request/response models
- `app/api/routes.py` — endpoints: chat (SSE), documents upload/list/delete, conversations, system status
- `app/rag/pipelines.py` — both pipeline implementations + SSE event protocol
- `app/rag/retriever.py` — fastembed Embedder + ChromaDB VectorStore
- `app/rag/ingestion.py` — markitdown parsing, chunking, indexing, doc deletion
- `app/rag/prompts.py` — system prompts and context formatting
- `app/llm/dashscope.py` — OpenAI-compatible client, thinking suppression, streaming, cost estimate
- `app/llm/jev_engine.py` — Jev-style decision wrapper (rerank / sufficiency+routing / verification)
- `scripts/` — smoke tests and validated experiments (keep them runnable)
- `tests/test_basic.py` — hermetic tests (no models, no network)

## Local Contracts

- All configuration via `JEVRAG_*` env vars; defaults must match `backend/.env.example`
- SSE event types are a frontend contract: `meta | status | retrieval | decision | rerank |
  routing | sources | llm_start | delta | done | error | ping` — coordinate with `src/AGENTS.md`
  before changing them
- Jev decisions run in threads (`asyncio.to_thread`); the jev-style adapter serializes model calls
- Long LLM streams bridge to async via `asyncio.to_thread(next, it, sentinel)` — keep it
- Errors inside a stream become `{"type":"error"}` frames, never dropped connections
- Model calls that can fail must degrade: verification is best-effort; jev load failure disables
  hybrid mode with a clear error, never crashes startup

## Work Guidance

- Rerank pattern (validated in `scripts/experiment_rerank*.py`): ONE `decide()` call, state =
  `"Question: {query}"`, one noul question per passage with the passage text embedded in the
  instructions. Do not revert to shared-state generic statements (they do not discriminate).
- Sufficiency + routing share one `decide()` call (state = question + truncated passages).
- `enable_thinking: false` is attempted first for Dashscope; on `BadRequestError` retry without
  it and filter `reasoning_content` deltas.
- Truncation knobs (`jev_rerank_char_limit`, `jev_context_char_limit`) exist to control decision
  latency on CPU — tune there, not by removing decisions.

## Verification

- `cd backend && .venv/bin/python -m pytest tests -v` (hermetic)
- `cd backend && .venv/bin/python -m scripts.smoke_jev` (needs models built)
- End-to-end SSE check: `curl -N -X POST localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"message":"...","mode":"hybrid"}'`

## Child DOX Index

| Child | Scope |
| --- | --- |
| (none) | `app/` subfolders are single-purpose modules; no child docs needed yet |
