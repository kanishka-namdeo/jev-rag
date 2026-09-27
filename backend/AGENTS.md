# Backend DOX

## Purpose

- Own the Python FastAPI service: two RAG pipelines (traditional, hybrid), the local Jev-style
  decision engine (System One), ingestion, embeddings/vector store, SQLite persistence, and the
  SSE chat protocol consumed by the frontend.

## Ownership

- `app/main.py` — app factory, lifespan (model warm-up), router mounting (`/api/*` and `/backend-api/*`)
- `app/config.py` — all settings (env prefix `JEVRAG_`, `backend/.env`), LLM price table, bench knobs
- `app/db.py` — SQLAlchemy models: Document, Conversation, Message (+trace JSON), BenchRun, BenchResult
- `app/schemas.py` — pydantic request/response models
- `app/api/routes.py` — endpoints: chat (SSE), documents upload/list/delete, conversations, system status
- `app/api/bench_routes.py` — benchmark endpoints: scenarios catalog, run lifecycle (POST/GET/DELETE), results
- `app/bench/scenarios.py` — scenario registry: 6 corpora × 48 ground-truth QA (reference answers, gold
  files, answerability, stress tags) — the benchmark's source of truth
- `app/bench/corpora/<scenario>/*.md` — scenario documents (bench- prefixed filenames)
- `app/bench/metrics.py` — deterministic retrieval metrics (hit@k, MRR, recall@k, file-level NDCG,
  Brier) — formulas are standard TREC/BeIR, see docs/benchmarking.md
- `app/bench/judge.py` — LLM-as-judge: absolute correctness/faithfulness/abstention (RAGAS/DeepEval
  definitions), MT-Bench pairwise with position swap, 8-canary self-test
- `app/bench/runner.py` — sequential orchestrator inside uvicorn: scenario re-ingest → both arms
  (production-identical prompts/knobs) → judge → aggregate → persist
- `app/rag/pipelines.py` — both pipeline implementations + SSE event protocol
- `app/rag/retriever.py` — fastembed Embedder + ChromaDB VectorStore (query supports doc_ids filter
  for scenario isolation)
- `app/rag/ingestion.py` — markitdown parsing, chunking, indexing, doc deletion
- `app/rag/prompts.py` — system prompts and context formatting (SHARED by pipelines AND bench arms)
- `app/llm/dashscope.py` — OpenAI-compatible client, thinking suppression, streaming, cost estimate
- `app/llm/jev_engine.py` — Jev-style decision wrapper (rerank / sufficiency+routing / verification);
  subprocess OOM auto-recovery; JEV_SCORE_N_CTX context control
- `scripts/` — smoke tests, validated experiments, bench result export (keep them runnable)
- `tests/` — hermetic tests (no models, no network): basic API, bench metrics math, scenario
  integrity, judge parsing/clamping/degradation, engine recovery

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

## Benchmark Contracts (app/bench)

- Scenario corpora and their ground truth live in `app/bench/scenarios.py` + `corpora/`;
  editing a corpus document invalidates the questions referencing it — update both together
- The judge model must stay model-family-independent from the pipeline generators
  (default `kimi-k2.5`; generators are qwen3.x-plus). Changing the judge model requires a
  full-run comparison to keep results comparable across runs
- Bench arms MUST mirror the production pipelines exactly (same prompts from
  `app/rag/prompts.py`, same thresholds/knobs) — the benchmark measures the shipped system,
  not a variant. When a pipeline changes, mirror it in `runner.py` and re-run
- Runs are sequential, one active at a time (single jev-score subprocess); results persist
  per question so partial results survive interruptions
- The runner retries the hybrid arm once after transient jev engine death, then fails fast;
  never convert engine-death into per-question "error" rows
- Aggregate summary formulas (`_summarize`) must stay aligned with the frontend's
  `liveSummary` fallback in `src/components/jevrag/bench/results-dashboard.tsx`

