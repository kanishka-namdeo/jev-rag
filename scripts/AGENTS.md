# Scripts DOX

## Purpose

- Own the setup / build / run scripts that make the project reproducible on a fresh machine.

## Ownership

- `setup_local_models.sh` — downloads Jev-Style GGUF (+ runtime files) and builds `jev-score`
  from llama.cpp (idempotent phases; safe to re-run)
- `setup_backend.sh` — creates `backend/.venv` via uv and installs requirements
- `backend_service.sh` — runs uvicorn (used by mini-services and the self-healing launcher)
- `dev.sh` — starts backend + frontend together for local development
- `init-fullstack-reference.sh` — reference copy of the sandbox init script (documentation only)
- `probe_public_gateway.sh` — endpoint reachability probe (models list, one chat per model,
  judge json_object smoke); reads key/base-url from env or `backend/.env` — never hardcodes credentials
- `backend/scripts/smoke_jev.py` — engine smoke test (noul warm-up, rerank, sufficiency+routing)
- `backend/scripts/build_public_scenarios.py` — materializes the five public benchmark scenarios
  from raw parquets into `app/bench/corpora/` + the manifest (merge-safe without `--force`)
- `backend/scripts/bench_resume.py` — resumable two-arm bench driver around the audited runner
  internals (per-question atomic commits; survives interruptions)
- `backend/scripts/experiment_rerank*.py` — validated decision-pattern experiments (do not delete;
  they document why the rerank pattern looks the way it does)
- `backend/scripts/experiment_single_model_routing.py` — validated experiments for the
  single-LLM decision slots (effort routing, retrieval-need, best-of-2 selection, citation
  check) backing `docs/jev-improvements-research.md` (do not delete; run with the backend
  stopped — memory discipline)
- `backend/scripts/export_bench_results.py` — exports a completed bench run to
  `docs/benchmark-results.md` + machine-readable JSON in `backend/data/bench_exports/`
- `backend/scripts/_merge_par_run.py` — merges per-scenario parallel-run
  DBs into one canonical `backend/data_merged/app.db`. Accepts CLI args:
  `--run-ids` (scenario:run_id pairs), `--data-dirs`, `--arms`, `--scenarios`,
  `--label`. Dedupes by scenario/question/arm; picks each scenario's *completed*
  run so a later in-flight retry cannot win the tie-break. Creates one unified
  `bench_runs` row. Idempotent (drops + rebuilds `data_merged/` on re-run).
  Usage: `.venv/bin/python scripts/_merge_par_run.py --arms base,gate-none --scenarios squad,hotpotqa`
- `scripts/run_parallel_bench.sh` — launches parallel benchmark workers, one per
  scenario on separate `JEVRAG_DATA_DIR`s (`backend/data_par/<scenario>/`).
  Uses `setsid nohup` to detach workers. Creates metadata file with run IDs.
  Usage: `bash scripts/run_parallel_bench.sh --arms "base,gate-none" --scenarios "squad,hotpotqa"`
- `scripts/check_parallel_bench.sh` — checks status of running parallel workers.
  Shows per-scenario progress from log files. Exit 0 when all completed.
  Usage: `bash scripts/check_parallel_bench.sh [--json]`
- `analyze_bench_run.py` / `analyze_per_scenario.py` / `bench_progress.py` / `diagnose_v2_losses.py` /
  `diagnose_public_bench.py` — run analysis/diagnostics over the bench DB (repo-anchored paths)
- `measure_jev_memory.py` / `verify_jev_flags.py` / `verify_jev_runtime_parity.py` — jev-score
  memory/parity probes (repo-anchored paths)
- `validate_readme.py` — README hygiene audit: link/anchor/image existence, `<details>`
  balance, secret-pattern scan (run before pushing README changes)
- `render_social_preview.py` + `social_preview.html` — regenerates the repo social
  preview card (Playwright, 1280×640 @2x) into `docs/assets/img/social-preview.png`;
  update the HTML source, re-render, then upload via repo Settings (the REST upload
  endpoint is closed to PATs)
- `test-assets/` — sample documents for manual testing (unindexed)

## Local Contracts

- Scripts must be idempotent and safe to re-run (size checks, resume flags)
- **Machine-independent**: scripts resolve the repo root from their own location
  (`$(dirname $0)/..` / `Path(__file__)`), never hardcode absolute paths, and avoid
  GNU-only coreutils (file sizes via `python3`, not `stat -c%s`). Mirror indexes are
  opt-in env overrides (`JEVRAG_PIP_INDEX_URL`, `UV_INDEX_URL`), never baked in
- Downloads must fail fast on stalls (timeouts + retries) and always resume (`-C -`)
- No secrets in scripts; credentials only via env files
- `setup_local_models.sh` re-applies the JEV_SCORE_N_CTX runtime patch after every fresh
  download (memory trim) — if the upstream runtime file changes shape, port the patch
  manually and update the script's matcher
- Changes to setup behavior must update `docs/setup.md` in the same commit (it is the
  binding fresh-machine guide)

## Verification

- Re-run each setup script after editing it; it must reach "STATUS: SUCCESS" without side effects
  on an already-provisioned machine

## Child DOX Index

| Child | Scope |
| --- | --- |
| (none) | Flat script directory |
