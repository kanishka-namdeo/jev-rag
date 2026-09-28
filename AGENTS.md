# Jev-RAG DOX

- DOX is highly performant AGENTS.md hierarchy installed here
- Agent must follow DOX instructions across any edits

## Core Contract

- AGENTS.md files are binding work contracts for their subtrees
- Work products, source materials, instructions, records, assets, and durable docs must stay understandable from the nearest applicable AGENTS.md plus every parent AGENTS.md above it

## Read Before Editing

1. Read the root AGENTS.md
2. Identify every file or folder you expect to touch
3. Walk from the repository root to each target path
4. Read every AGENTS.md found along each route
5. If a parent AGENTS.md lists a child AGENTS.md whose scope contains the path, read that child and continue from there
6. Use the nearest AGENTS.md as the local contract and parent docs for repo-wide rules
7. If docs conflict, the closer doc controls local work details, but no child doc may weaken DOX

Do not rely on memory. Re-read the applicable DOX chain in the current session before editing.

## Update After Editing

Every meaningful change requires a DOX pass before the task is done.

Update the closest owning AGENTS.md when a change affects:

- purpose, scope, ownership, or responsibilities
- durable structure, contracts, workflows, or operating rules
- required inputs, outputs, permissions, constraints, side effects, or artifacts
- user preferences about behavior, communication, process, organization, or quality
- AGENTS.md creation, deletion, move, rename, or index contents

Update parent docs when parent-level structure, ownership, workflow, or child index changes. Update child docs when parent changes alter local rules. Remove stale or contradictory text immediately. Small edits that do not change behavior or contracts may leave docs unchanged, but the DOX pass still must happen.

## Hierarchy

- Root AGENTS.md is the DOX rail: project-wide instructions, global preferences, durable workflow rules, and the top-level Child DOX Index
- Child AGENTS.md files own domain-specific instructions and their own Child DOX Index
- Each parent explains what its direct children cover and what stays owned by the parent
- The closer a doc is to the work, the more specific and practical it must be

## Child Doc Shape

- Create a child AGENTS.md when a folder becomes a durable boundary with its own purpose, rules, responsibilities, workflow, materials, or quality standards
- Work Guidance must reflect the current standards of the project or user instructions; if there are no specific standards or instructions yet, leave it empty
- Verification must reflect an existing check; if no verification framework exists yet, leave it empty and update it when one exists

Default section order:
- Purpose
- Ownership
- Local Contracts
- Work Guidance
- Verification
- Child DOX Index

## Style

- Keep docs concise, current, and operational
- Document stable contracts, not diary entries
- Put broad rules in parent docs and concrete details in child docs
- Prefer direct bullets with explicit names
- Do not duplicate rules across many files unless each scope needs a local version
- Delete stale notes instead of explaining history
- Trim obvious statements, repeated rules, misplaced detail, and warnings for risks that no longer exist

## Closeout

1. Re-check changed paths against the DOX chain
2. Update nearest owning docs and any affected parents or children
3. Refresh every affected Child DOX Index
4. Remove stale or contradictory text
5. Run existing verification when relevant
6. Report any docs intentionally left unchanged and why

## User Preferences

When the user requests a durable behavior change, record it here or in the relevant child AGENTS.md

## Purpose

- Jev-RAG: a local-first hybrid RAG system over user-uploaded documents with two pipelines:
  1. **Traditional RAG** — embedding retrieval → cloud LLM (System Two) → cited answer
  2. **Hybrid RAG** — a local, open-source Jev-style decision model (System One) reranks passages,
     gates context sufficiency, routes between cloud models, and verifies groundedness;
     the cloud LLM (System Two) writes the final cited answer
- Everything except the cloud LLM endpoint runs locally (embeddings, vector store, decision model, DBs)

## Project

- Stack: FastAPI + Uvicorn · ChromaDB (embedded) · fastembed (ONNX CPU) · jev-style 0.8B GGUF on
  llama.cpp (`jev-score` scorer) · markitdown · langchain-text-splitters · SQLAlchemy/SQLite ·
  OpenAI SDK → Dashscope · Next.js 16 (App Router) + TypeScript + Tailwind 4 + shadcn/ui + zustand
- Cloud LLM endpoint (OpenAI-compatible): `https://coding-intl.dashscope.aliyuncs.com/v1`
  - `qwen3.7-plus` — default workhorse (fast, cheap, strong synthesis)
  - `qwen3.6-plus` — deep-reasoning route (always-on chain-of-thought)
- Setup: **[docs/setup.md](docs/setup.md)** is the binding fresh-machine guide. In short:
  `scripts/setup_local_models.sh` (models + jev-score build) then `scripts/setup_backend.sh`
  (backend venv) then `scripts/dev.sh` (backend + frontend). Copy `backend/.env.example` →
  `backend/.env` first. Setup scripts must resolve the repo root from their own location
  (never hardcode absolute paths) and stay idempotent.
- Backend tests: `cd backend && .venv/bin/python -m pytest tests -v`
- Frontend lint: `bun run lint`
- Frontend dev: `bun run dev` (port 3000); backend: port 8000 (proxied via `/backend-api/*` rewrite)

## Project-Wide Contracts

These bind EVERY agent working in this repository, regardless of whether the user's current
instructions mention them. No child doc may weaken them.

- **Popular open-source first.** Use latest, widely-adopted libraries for any new capability;
  do not re-invent wheels unless absolutely necessary. State the library choice in the PR/commit.
- **Ground claims with search.** Before assuming a library version, API shape, model capability,
  or "best practice", verify with a web search when feasible; cite sources in docs/PRs.
- **Local-first.** All data and inference except the Dashscope LLM endpoint must run on-device:
  no external vector DB, no external embedding APIs, no telemetry.
- **Secrets never enter git.** API keys only in `backend/.env` (gitignored). Keep
  `backend/.env.example` current with every config change. Scan staged content before pushing.
- **Debuggable by default.** Structured logging via module loggers (`jevrag.*`), env-driven
  config only (no hardcoded paths/keys), small functions, and a pipeline trace persisted per message.
- **Live-browser verification for UI work.** Any frontend change must be exercised in a real
  browser (agent-browser or equivalent) before being called done — "it compiles" is not done.
- **Model usage.** Generation defaults to `qwen3.7-plus`; `qwen3.6-plus` only for hard-reasoning
  workloads. Never invent models not present on the endpoint.
- **Jev-faithful System One.** Local decisions use typed calibrated primitives (noul/choice/score)
  via the `jev-style` package; they never generate prose. New decision points go in
  `backend/app/llm/jev_engine.py`.
- **Benchmarks guard the pipelines.** Any change to retrieval, prompts, Jev decision patterns,
  model routing, or generation settings MUST re-run the benchmark smoke (`POST /api/bench/runs`
  with one scenario) and record the delta vs `docs/benchmark-results.md` in the PR/commit message.
  Full runs re-export results via `backend/scripts/export_bench_results.py`. Methodology is
  binding: `docs/benchmarking.md` (judge must stay model-family-independent from the generators).
- **Sandbox memory discipline.** The jev-score subprocess needs ~1.5GB RSS and the sandbox has
  4GB total: during any long local-model run, avoid launching browsers, recompiling the frontend,
  or starting duplicate model processes. The engine auto-reloads on subprocess death
  (`JevEngine._try_load`); never remove that recovery path.
- **Tests and lint stay green.** Backend pytest and `bun run lint` must pass before every push.
- **Commit and push at milestones.** Small, descriptive commits; push to `origin/main` after each
  meaningful milestone (feature, fix, docs).

## Permissions

- Allowed without asking: refactors that keep tests green, doc updates, adding dependencies that
  are popular and permissively licensed, tuning retrieval/Jev knobs via `backend/.env.example`.
- Ask before: changing the API protocol (`/backend-api/*` SSE event schema), swapping the local
  decision model or embedding model, changing the two-pipeline product concept, deleting migration
  paths for stored data, adding any external service dependency.

## Child DOX Index

| Child | Scope |
| --- | --- |
| [backend/AGENTS.md](backend/AGENTS.md) | FastAPI service, RAG pipelines, Jev-style engine, ingestion, storage, benchmark harness, tests |
| [src/AGENTS.md](src/AGENTS.md) | Next.js frontend: chat UI, trace panel, documents, benchmarks dashboard, store and API client |
| [scripts/AGENTS.md](scripts/AGENTS.md) | Setup, build and run scripts for models, backend, dev workflow, bench export |
| [docs/AGENTS.md](docs/AGENTS.md) | Durable design docs: architecture, hybrid pipeline, API protocol, benchmarking methodology & results |

Intentionally unindexed local or generated roots: `node_modules/`, `.next/`, `backend/.venv/`,
`backend/data/`, `models/`, `vendor/`, `logs/`, `mini-services/`, `download/`, `upload/`,
`skills/`, `.zscripts/`, `scripts/research/`, `scripts/test-assets/`.
