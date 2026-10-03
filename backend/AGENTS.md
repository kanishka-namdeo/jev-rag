# Backend DOX

## Purpose

- Own the Python FastAPI service: two RAG pipelines (traditional, hybrid), the local Jev-style
  decision engine (System One), ingestion, embeddings/vector store, SQLite persistence, and the
  SSE chat protocol consumed by the frontend.

## Ownership

- `app/main.py` — app factory, lifespan (model warm-up), router mounting (`/api/*` and `/backend-api/*`)
- `app/config.py` — all settings (env prefix `JEVRAG_`, `backend/.env`), LLM price table, bench knobs;
  server fields `host` (default `127.0.0.1` — loopback, because the app has no auth) and
  `frontend_origin` (+ its `cors_origins` property, never a wildcard) back the shipped reachability
  default; resolves relative paths and locates `backend/.env` against the repo root (CWD-independent —
  see docs/setup.md §“Where paths resolve”)
- `app/db.py` — SQLAlchemy models: Document, Conversation, Message (+trace JSON), BenchRun, BenchResult
- `app/schemas.py` — pydantic request/response models
- `app/api/routes.py` — endpoints: chat (SSE), documents upload/list/delete, conversations, system status
- `app/api/bench_routes.py` — benchmark endpoints: scenarios catalog, run lifecycle (POST/GET/DELETE), results
- `app/bench/scenarios.py` — scenario registry: 6 internal corpora × 48 ground-truth QA plus
  5 public-benchmark scenarios × 98 QA (references, gold files, answerability, stress tags
  when the manifest was built) — the benchmark's source of truth
- `app/bench/corpora/<scenario>/*.md` — scenario documents (bench- prefixed filenames)
- `app/bench/metrics.py` — deterministic retrieval metrics (hit@k, MRR, recall@k, file-level NDCG,
  Brier) — formulas are standard TREC/BeIR, see docs/benchmarking.md; RAGAS-style LLM-based
  context precision/recall metrics (diagnose ranking quality vs coverage gaps)
- `app/bench/judge.py` — LLM-as-judge: absolute correctness/faithfulness/abstention (RAGAS/DeepEval
  definitions), MT-Bench pairwise with position swap, 9-canary self-test; `MultiJudgeEnsemble`
  aggregates across multiple independent judges (mean for continuous scores, majority vote
  for categorical decisions, 1−CV agreement)
- `app/bench/runner.py` — sequential orchestrator inside uvicorn: scenario re-ingest → both arms
  (production-identical prompts/knobs) → judge → aggregate → persist
- `app/rag/pipelines.py` — both pipeline implementations (hybrid = v3 score-feature-gate
  design, docs/rag-upgrade-2026.md §3.3), the SSE event protocol, and the shared policy
  functions (`parse_citations`, `apply_battery_policy`, `citation_summary`,
  `composite_quality`, `sum_token_usage`) imported by the bench runners
- `app/rag/retriever.py` — fastembed Embedder + ChromaDB VectorStore (query supports doc_ids filter
  for scenario isolation)
- `app/rag/prompts.py` — system prompts, conflict/direct suffixes, decompose/rewrite utility
  prompts, and context formatting (SHARED by pipelines AND bench arms)
- `app/llm/dashscope.py` — OpenAI-compatible client, thinking suppression + per-call override,
  streaming + non-streaming `complete()`, cost estimate
- `app/llm/jev_engine.py` — Jev-style decision wrapper (v2 slots: effort_routing /
  rerank / screen_passages / sufficiency / select_best_candidate /
  verify_citations_and_quality / legacy verify_groundedness);
  subprocess OOM auto-recovery; JEV_SCORE_N_CTX context control
- `app/rag/ingestion.py` — markitdown parsing, chunking, indexing, doc deletion
- `scripts/` — smoke tests, validated experiments, bench result export, query robustness testing,
  statistical power analysis (keep them runnable)
- `tests/` — hermetic tests (no models, no network): basic API, bench metrics math, scenario
  integrity, judge parsing/clamping/degradation, engine recovery, v2 policy functions
  (`tests/test_v2_pipeline.py`) — keep new decision-shape changes covered there first

## GPU Acceleration

- **jev-score** (llama.cpp): Built with CUDA support (`GGML_CUDA=ON`). Uses GPU automatically when available.
- **Embedder** (fastembed): Configured to use `CUDAExecutionProvider` with automatic CPU fallback (see `app/rag/retriever.py:65-80`).
- **Cross-encoder** (ONNX): Configured to use `CUDAExecutionProvider` with automatic CPU fallback (see `app/rag/crossenc.py:160-180`).

### WSL2 GPU Limitation

ONNX Runtime's CUDA provider does **not** work with WSL2's GPU virtualization layer. The paravirtualized GPU driver (`/dev/dxg`) lacks full CUDA support needed by ONNX Runtime. This causes "no CUDA-capable device is detected" errors even though `nvidia-smi` shows the GPU.

**Impact**: Embedder and cross-encoder automatically fall back to CPU in WSL2. jev-score works on GPU.

**Fallback behavior**: When CUDA initialization fails, the system logs a warning and automatically falls back to CPU execution. This ensures the pipeline remains functional in WSL2 and other environments with limited GPU support.

**Workaround**: For full GPU acceleration, use native Linux (not WSL2) or wait for ONNX Runtime to support WSL2 GPU passthrough.

**Verification**: Run `backend/scripts/gpu_test.py` to check GPU status for each component.

## Local Contracts

- All configuration via `JEVRAG_*` env vars. Adding (or re-defaulting) a setting is a three-way
  same-commit obligation: the `app/config.py` default **+** a `backend/.env.example` line **+** the
  `docs/configuration.md` row. `backend/tests/test_server_defaults.py` fails on code↔template drift
  (and checks the declared defaults, never a live `Settings()`, so a developer's own `.env` cannot
  decide the outcome); only the doc row is outside its reach — keep it honest by hand
- Configured paths resolve relative to the repo root (never the process CWD) — keep that
  anchoring intact in `app/config.py` when adding new path settings
- SSE event types are a frontend contract: `meta | status | retrieval | decision | rerank |
  routing | sources | llm_start | delta | done | error | ping` — coordinate with `src/AGENTS.md`
  before changing them. The `routing` event carries v2 effort routing
  (`{effort, model, probabilities, confidence}`); `done` may carry `effort`, `quality_score`,
  `best_of`, `retried`, `rewritten_query`, `citations_verified`, and (bench-only)
  `context_used` + `context_chunks` (formatted block vs per-chunk texts for metrics)
- Jev decisions run in threads (`asyncio.to_thread`); the jev-style adapter serializes model calls
- Long LLM streams bridge to async via `asyncio.to_thread(next, it, sentinel)` — keep it
- Errors inside a stream become `{"type":"error"}` frames, never dropped connections
- Model calls that can fail must degrade: verification/citation checks are best-effort;
  decomposition falls back to the original query; rewrite failure keeps the original;
  jev load failure disables hybrid mode with a clear error, never crashes startup
- The v2 policy functions in `pipelines.py` are shared with the bench runner — changing a
  threshold formula changes BOTH arms by contract

## Work Guidance

- Rerank pattern (validated in `scripts/experiment_rerank*.py`): ONE `decide()` call, state =
  `"Question: {query}"`, one noul question per passage with the passage text embedded in the
  instructions. Do not revert to shared-state generic statements (they do not discriminate).
  The same passage-in-instructions rule holds for the battery, best-of-2 candidates, and
  citation questions (validated in `scripts/experiment_single_model_routing.py`).
- Battery threshold policy is ORDERED: injection drop > conflict-block > evidence drop, with
  rerank relevance ≥ 0.5 as the rescue for weak-evidence-but-clearly-relevant passages.
- Best-of-2 candidates are generated CONCURRENTLY (asyncio.gather) — one thinking-off, one
  thinking-on; selection ranks candidates, never hard-gates on absolute P(grounded).
- Conflict-blocked passages keep their [n] citation labels — they move to the flagged prompt
  section but stay citation-checkable.
- `enable_thinking: false` is attempted first for Dashscope; on `BadRequestError` retry without
  it and filter `reasoning_content` deltas. Per-call `enable_thinking` overrides the global
  setting (best-of-2 candidate B).
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
- Runs are sequential, one active at a time **per process** (single jev-score subprocess);
  results persist per question so partial results survive interruptions
- **Parallel workers**: on a workstation (≥12 GB RAM free, ~2.3 GB RSS per worker) run one
  worker process per scenario on separate `JEVRAG_DATA_DIR`s — `scripts/run_parallel_bench.sh`
  (`--driver testbench|resume`, `--max-parallel`), `scripts/check_parallel_bench.sh`,
  `backend/scripts/_merge_par_run.py`. The in-process single-run contract above is
  unchanged; parallelism comes from independent processes, never from sharing a runner or
  a data dir. Full procedure and worker contracts:
  [docs/parallel-bench-runbook.md](../docs/parallel-bench-runbook.md)
- `scripts/run_testbench.py` prints `RUN_ID=<uuid>` before model warm-up and records
  `progress_total` up front — the launcher and the monitor depend on both; the DB, not the
  log, is the progress source of truth
- **The complete Layer-2 suite is the 9 pre-declared arms** of
  [docs/testbench-design.md](../docs/testbench-design.md); its current record is merged run
  `36abefc6` — 882 triples, 0 error rows, 5 workers
  ([docs/testbench-results-layer2-full9.md](../docs/testbench-results-layer2-full9.md)).
  `scripts/run_parallel_bench.sh --arms` defaults to only the 4-arm H-GATE family, so a full
  run must pass all nine explicitly
- Merged-DB analysis chain: `backend/scripts/analyze_testbench.py` (report + `.json` twin) →
  `backend/scripts/plot_testbench_arms.py` (chart reusing `analyze()`, so the PNG cannot drift
  from the report). Re-running the analyzer overwrites the report's generated tables, so the
  curated section below its `---` rule must be re-applied
- Knobs a run used are persisted nested under `bench_runs.config["base"]` — thresholds (e.g.
  `gate_score_threshold`, `jev_sufficiency_threshold`) must be read from there, with the top
  level only as the legacy flat-config fallback; a flat-only read falls back to the default and
  reports a phantom operating point in every published calibration table.
  `scripts/run_testbench.py::base_config()` is the single recording point — every knob the
  analyzer reads must be added there, and `tests/test_analyze_testbench.py` fails when a
  recorded knob stops resolving through the analyzer lookup
- Gate calibration is scored on the FIRST gate reading (the one that chose the path —
  `app.bench.stats.first_gate_score`) vs gold-in-final-top4 coverage, never on the
  done-event `sufficiency_p` (re-evaluated post-retry on the hard path) vs answerability
  (degenerate on all-answerable suites). The answerability table is kept for continuity
  but labeled as such everywhere it is rendered
- The runner retries the hybrid arm once after transient jev engine death, then fails fast;
  never convert engine-death into per-question "error" rows
- Aggregate summary formulas (`_summarize`) must stay aligned with the frontend's
  `liveSummary` fallback in `src/components/jevrag/bench/results-dashboard.tsx` — including
  the pairwise judge-error exclusion (error rows leave the win-rate denominator on both
  sides) and the gate coverage table (gold-in-final-top4 basis preferred over the
  degenerate answerability basis on all-answerable suites)

