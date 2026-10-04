# Scripts DOX

## Purpose

- Own the setup / build / run scripts that make the project reproducible on a fresh machine.

## Ownership

- `setup_local_models.sh` — downloads Jev-Style GGUF (+ runtime files) and builds `jev-score`
  from llama.cpp (idempotent phases; safe to re-run)
- `setup_backend.sh` — creates `backend/.venv` via uv and installs requirements
- `backend_service.sh` — runs uvicorn (used by mini-services and the self-healing launcher)
- `dev.sh` — starts backend + frontend together for local development; exports
  `NEXT_TELEMETRY_DISABLED=1` (local-first contract — the same var prefixes the
  `dev`/`build`/`start` scripts in `package.json`)
- `init-fullstack-reference.sh` — reference copy of the sandbox init script (documentation only)
- `probe_public_gateway.sh` — endpoint reachability probe (models list, one chat per model,
  judge json_object smoke); reads key/base-url from env or `backend/.env` — never hardcodes
  credentials. Strips `\r` from `.env` values (a CRLF env file is the Windows default and a CR
  in the header or URL makes every call fail). It is a gate: `STATUS: SUCCESS` + exit 0 only
  when all three models and the judge json_object check answered, exit 1 otherwise
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
  DBs into one canonical merged DB (default `backend/data_merged/app.db`).
  Reads `parallel_run_meta.json` by default (`--meta`, `--data-par`, `--out`);
  an unset `--meta` resolves under the `--data-par` / `JEVRAG_DATA_PAR_ROOT` root so one
  scratch root drives launch → monitor → merge, and `--meta ''` disables the meta file.
  `--run-ids` / `--data-dirs` override it, `--scenarios` selects scenarios and
  `--arms` narrows rows by `bench_results.mode`. Per scenario it picks the
  *completed* run with the most rows (PARTIAL warning + most-rows fallback when
  nothing completed), dedupes by scenario/question/mode with fresh row ids, and
  writes one unified `bench_runs` row. Sources open read-only. Exits
  0 merged / 2 missing source / 3 unreadable source / 4 zero-row scenario.
  Idempotent (rebuilds the merged DB on re-run).
  **A new published record gets its own `--out` dir** (`backend/data_merged_r2/…`): the merge
  rebuilds its output and mints a *fresh* unified run id every call, so re-using the default
  path silently orphans the run id the docs cite and makes that record un-re-analysable.
  Usage: `.venv/bin/python scripts/_merge_par_run.py --arms base,gate-none --scenarios squad,hotpotqa`
- `backend/scripts/analyze_testbench.py` — per-arm metrics + paired stats (exact McNemar,
  bootstrap CI, BH-FDR) for a testbench run; `--out FILE` writes the Markdown report and a
  `.json` twin
- `backend/scripts/plot_testbench_arms.py` — renders the Layer-2 arm chart **from a merged
  run's DB** by reusing `analyze_testbench.analyze()`, so the PNG cannot drift from the
  report it illustrates (correctness + Wilson CI + Δ/q, p50 latency, escalation rate, cost).
  Needs `matplotlib` (declared in `backend/requirements.txt`). It is the **only** generated
  chart in the repo and every figure on it is measured — architecture and pipeline diagrams
  are Mermaid in the Markdown instead, so there is no illustrative-number image left to
  mistake for a result.
  Usage: `JEVRAG_DATA_DIR=data_merged_r2 .venv/bin/python scripts/plot_testbench_arms.py RUN_ID --out ../docs/assets/img/layer2-arm-results.png`
  (point `JEVRAG_DATA_DIR`/`--base` at the merged DB of the run the record page documents —
  currently `backend/data_merged_r2` for run `4ec32592`; re-render whenever that run changes)
- `scripts/run_parallel_bench.sh` — the parallel-bench entrypoint: launches one detached
  worker per scenario on separate `JEVRAG_DATA_DIR`s (`backend/data_par/<scenario>/`,
  override root with `JEVRAG_DATA_PAR_ROOT` or `--data-par`, flag wins).
  `--driver testbench|resume` maps flags to
  `backend/scripts/run_testbench.py` or `bench_resume.py`, so both suites parallelise.
  `--max-parallel N` (default 5) queues instead of oversubscribing RAM, `--resume s:id,...`
  resumes, `--dry-run` prints commands and touches nothing. Polls (bounded, `RUN_ID_TIMEOUT`)
  for the worker's `RUN_ID=` line instead of sleeping, refuses to start on top of live
  workers owning the same dirs, and writes `data_par/parallel_run_meta.json`.
  **`--arms` defaults to the 4-arm H-GATE family, not the 9-arm Layer-2 suite** — a launch
  that omits it silently runs 4 of the 9 declared arms, so always pass the arm set.
  **Point `--data-par` at a fresh root for every new full run**, never a previous run's: workers
  skip triples already in their own DB, so a reused root silently blends two draws into one run.
  A fresh root also leaves every worker with an empty `fastembed_cache`, and N simultaneous HF
  downloads deadlock (0-byte `*.incomplete`, no progress, workers at ~2% CPU) — seed the
  cross-encoder into the shared cache and copy a warm `fastembed_cache` per worker before
  launching, and treat a first-minutes `0/?` progress row as normal unless those files are 0 bytes.
  Usage: `bash scripts/run_parallel_bench.sh --arms "base,gate-none" --scenarios "squad,hotpotqa"`
- `scripts/check_parallel_bench.sh` — status of parallel workers, read from each worker's
  `app.db` (`bench_runs.status/progress_*`, `bench_results` counts) plus pid liveness —
  never from log text, which is human-formatted. `--json` for machines, `--data-par PATH`
  to report a scratch root. Under `wsl -- bash -ic` the shell status is unreliable — read
  `exit_code` from `--json`.
  Exits 0 all completed / 1 still running / 2 nothing to report / 3 dead-or-partial
  (resume before merging).
  Usage: `bash scripts/check_parallel_bench.sh [--json] [--data-par PATH]`
- `analyze_bench_run.py` / `analyze_per_scenario.py` / `bench_progress.py` / `diagnose_v2_losses.py` /
  `diagnose_public_bench.py` — run analysis/diagnostics over the bench DB (repo-anchored paths)
- `measure_jev_memory.py` / `verify_jev_flags.py` / `verify_jev_runtime_parity.py` — jev-score
  memory/parity probes (repo-anchored paths)
- `validate_docs.py` — Markdown hygiene audit scoped to **documentation only** (repo-root
  `.md`, `docs/**`, `.github/**`, and every `AGENTS.md`; it excludes the benchmark corpora
  under `backend/app/bench/corpora/` and the unindexed roots, because those are test data and
  generated trees, not docs): relative link and image existence (including the outer target
  of a badge link, `[![alt](img)](target)`), heading anchors for **both** same-page `#frag`
  links and `page.md#frag` deep links, `<details>` balance, and a hardcoded secret-prefix
  check (`SECRET_PATTERNS` — three literal prefixes at `validate_docs.py:21`; it is **not**
  a general secret detector: a generic `sk-…` key or a classic `ghp_` PAT passes it. The
  real protection is the root AGENTS.md secrets contract: keys only ever in gitignored
  `backend/.env`, and scan staged content before pushing). Anchor slugs
  reproduce GitHub's own rule — lowercase, punctuation and emoji dropped, **every** remaining
  space becomes a hyphen with no collapsing or trimming (`## A — B` → `a--b`,
  `## 📸 Screenshots` → `-screenshots`, ``## Run `bf05f585` config`` keeps `bf05f585`), with a
  deliberate leniency for the leading-hyphen-stripped form. Measured against GitHub's render
  of the in-scope docs: 160/161 ids; the one deviation (an emoji plus U+FE0F keeps GitHub's
  invisible variation selector) is explained in the script. Markup is read from prose only
  (fences and inline code are not links), but anchor slugs keep inline-code text; the prefix
  check still reads raw text. An unreadable or undecodable file becomes an `ERROR:` line, never
  a traceback. Exit 1 on any error. Run it before pushing any docs change — it is a CI job,
  not an optional check. Formerly README-only (`validate_readme.py`), then briefly every
  tracked `.md`.
- `capture_ui_screenshots.py` — regenerates the four live-browser README shots
  (`docs/assets/img/{chat-compare,trace-panel,bench-lab,bench-charts}.png`) by driving the
  **running** app with Playwright: 1512x945 at device_scale_factor=1 (the pixel size the
  README already ships), light theme, repo-root-anchored, `--only`/`--base-url`/`--out-dir`.
  Chat half: New chat → Compare → the two `QUESTIONS` → close the trace panel (Compare
  auto-opens it, `store.ts::send`) → frame the last exchange from its question bubble →
  `chat-compare.png`; then View trace on the last hybrid answer → `trace-panel.png`.
  Bench half: switch to Benchmarks and wait — `BenchView.init()` auto-selects the newest
  **completed** run, and the dashboard renders blank metric cards and empty charts for a run
  with no judge `summary`, so refresh `bench-charts.png` only against a fully summarised run.
  Costs real cloud calls (two per question in Compare) and needs a Playwright-enabled
  interpreter (`playwright` is deliberately not a `backend/.venv` dependency, same as
  `render_social_preview.py`). **Capture against a production build** (`bun run build &&
  bun run start`) — `next dev` paints its dev-tools badge into every shot.
- `render_social_preview.py` + `social_preview.html` — regenerates the repo social
  preview card (Playwright, 1280×640 at **1×**) into `docs/assets/img/social-preview.png`.
  1× is required, not cosmetic: GitHub caps the social preview under 1 MB and recommends
  1280×640, and the old `device_scale_factor=2` render came out 2560×1280 / 1.07 MB.
  The script anchors both its HTML input and its PNG output to the repo root via
  `Path(__file__).resolve().parents[1]` (no hardcoded absolute paths). Run it with a
  Playwright-enabled interpreter (`playwright` is not in `backend/.venv`).
  Update the HTML source, re-render, then upload via repo Settings (the REST upload
  endpoint is closed to PATs) — that upload is a manual maintainer step
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
