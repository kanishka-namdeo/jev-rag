# Changelog

Milestone history for Jev-RAG. Each entry links to the commit that delivered it.
Dates are YYYY-MM-DD (commit date). Format is loosely inspired by
[Keep a Changelog](https://keepachangelog.com/), grouped by project phase.

## 2026-09-28 — Research: Jev beyond routing / single-model design

- **Research pass** (two websearch agents + local experiments):
  [docs/jev-improvements-research.md](docs/jev-improvements-research.md) answers "what if
  there were only one cloud model?" — routing degenerates into whether/how/how-many-times
  to invoke the single model, plus which candidate output to keep — with published evidence
  (Adaptive-RAG, CRAG, FrugalGPT/RouteLLM/Hybrid-LLM, verifiers/Speculative-RAG, TypeSafe's
  own patterns/cookbooks) and 11 ranked improvement patterns for Jev-style decision models
  in RAG pipelines.
- **Local validation experiments**
  (`backend/scripts/experiment_single_model_routing.py`): effort routing 3-way choice
  **9/12** (and the `no_retrieval` probability cleanly separates chat from doc questions —
  a safe skip-retrieval fast-path); best-of-2 selection picks the faithful answer
  (**0.973 vs 0.817**, one call); per-citation `supports/contradicts/says_nothing` check
  **3/3**. Includes a v2 pipeline proposal and a "what NOT to build" list from published
  negative results.

## 2026-09-28 — Presentable & documented

- **Repo beautification**: README with screenshots, results-at-a-glance tables, mermaid
  architecture diagram, guided quickstart and repository tour; Apache-2.0 `LICENSE`;
  this `CHANGELOG.md`; GitHub repo description + topics.
- **Bug fix** (found while screenshotting): the per-scenario **Hit@4 / MRR@10 charts** in the
  Benchmarks dashboard rendered empty because they read retrieval metrics from the wrong
  level of the summary object (`arm[field]` instead of `arm.retrieval[field]`).
  Correctness and faithfulness charts were unaffected.

## 2026-09-27 — Benchmarking & comparison (Phase 3)

- [`3a950d2`](https://github.com/kanishka-namdeo/jev-rag/commit/3a950d2) — **Benchmarks Lab UI**
  (scenario cards, live progress polling, results dashboard with metric cards + delta chips,
  four per-scenario comparison charts, pairwise / gate / rerank-lift panels, abstention table,
  per-question drill-down with full judge reasoning) · methodology doc · exported full-run
  results.
- **Full benchmark run completed**: 48 questions × 2 systems, 96 result rows, 0 errors, 31.9 min
  (run `9d894b6c`).
  Headline: hybrid correctness **93.8% vs 85.4%** (+8.4pp), earnings-distractor scenario
  **75% → 100%**, over-abstention **14% → 2.3%**, zero fabrications, Jev gate accuracy **91.7%**
  (Brier 0.077), pairwise win rate 54.2% (6W/40T/2L), judge self-test 8/8.
  Honest tradeoff documented: hybrid latency p50 30.5 s vs 1.5 s (three local decision calls).
- [`77993b2`](https://github.com/kanishka-namdeo/jev-rag/commit/77993b2) — run hygiene: memory
  trim per question, orphaned-run reaping at startup.
- [`be74274`](https://github.com/kanishka-namdeo/jev-rag/commit/be74274) ·
  [`48b94f5`](https://github.com/kanishka-namdeo/jev-rag/commit/48b94f5) — **OOM resilience**:
  `JEV_SCORE_N_CTX=8192` cap, engine reload + retry on subprocess death, `MALLOC_ARENA_MAX=2`.
  Root lesson recorded in DOX: no eslint/browser/node tooling during long local-model runs.
- [`472c2a0`](https://github.com/kanishka-namdeo/jev-rag/commit/472c2a0) — **benchmarking
  harness**: six scenario corpora (26 documents, 48 ground-truth QA pairs — techdocs, finance
  distractors, conditional policies, needle KB, multilingual EN/ZH/DE/FR, out-of-scope
  abstention) · deterministic retrieval metrics (hit@k, MRR, recall@k, file-level nDCG@10 —
  including a duplicate-gold-chunk fix) · independent LLM judge (`kimi-k2.5`, JSON-only,
  temperature 0, 8-canary self-test) for correctness/faithfulness + 3-way abstention ·
  MT-Bench pairwise with position swap + consistency audit · `bench_runs`/`bench_results`
  persistence · API under `/api` and `/backend-api` · 22 passing tests.
  Design was grounded in a dedicated research pass over RAGAS / DeepEval / ARES / G-Eval /
  MT-Bench / GRAB-RAG / AbstentionBench methodology.

## 2026-09-27 — System & docs (Phase 2)

- [`ab7daae`](https://github.com/kanishka-namdeo/jev-rag/commit/ab7daae) — **DOX framework**
  (root `AGENTS.md` with project-wide contracts + child docs for `backend/`, `src/`, `scripts/`,
  `docs/`) · docs (architecture, hybrid design, API) · CI workflow (hermetic pytest + lint) ·
  Caddy proxy + Next rewrite so the API works in all hosting contexts · self-healing backend
  (`/api/ensure-backend` spawns uvicorn detached) + SSE retry after re-ensure.
- Live-browser verification of every surface: traditional chat, hybrid chat (context 0.84,
  grounded 93%), compare mode side-by-side, upload via UI, trace panel with all four Jev
  decisions, mobile layout, zero console errors.

## 2026-09-27 — Initial system (Phase 1)

- [`a976e87`](https://github.com/kanishka-namdeo/jev-rag/commit/a976e87) — **first working
  hybrid RAG system**:
  - Backend (FastAPI): Dashscope client with thinking-suppression + cost estimation; local
    Jev engine (Jev-Style-0.8B GGUF on a custom llama.cpp `jev-score` build); ingestion via
    markitdown + langchain-text-splitters + fastembed (multilingual MiniLM) + ChromaDB;
    traditional and hybrid pipelines with an SSE event protocol; conversations/messages/trace
    persistence in SQLite; 5 hermetic tests.
  - Frontend (Next.js 16 + Tailwind 4 + shadcn/ui): chat with compare rows, markdown +
    citation chips, trace panel with probability bars, document upload, conversations,
    status pill, dark mode.
  - **Measured decision patterns** (the core research result): generic shared-state statements
    give zero discrimination (0.97 vs 0.02 in a bad pattern), while passage-text-in-question
    single-call scoring wins — adopted for `rerank_chunks`.
  - Local System One selection was grounded in verified HF metadata: Jev itself is
    closed-weights/cloud-only, so the open stand-in is Jev-Style-0.8B-Decision-v3 (Q4_K_M,
    529,296,864 bytes, Apache-2.0); endpoint model split chosen from published strengths
    (qwen3.7-plus = faster/cheaper/agentically stronger default; qwen3.6-plus = always-on CoT
    for the deep-reasoning route).
