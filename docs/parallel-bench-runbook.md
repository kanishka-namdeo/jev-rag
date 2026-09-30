# Parallel Benchmark Runbook

How to run a full benchmark with several workers at once on a workstation, and how to
turn the scattered per-worker results back into one analysable run. The serial path
(UI or `POST /api/bench/runs`) is unchanged and still the right choice for smokes;
this doc covers the parallel path only. Methodology and metric definitions are owned by
[benchmarking.md](benchmarking.md) — nothing here changes what a run *measures*, only how
it is *executed*.

## When to use which

| Situation | Use |
| --- | --- |
| One-scenario smoke after a pipeline/prompt change | serial: UI or `POST /backend-api/bench/runs` |
| Full internal suite (6 scenarios × 2 arms) or public suite (5 scenarios × up to 9 arms) | parallel: this runbook |
| Anything you must finish inside one wall-clock window | parallel + `--window-minutes`, then resume |

The in-process `BenchRunner` (`backend/app/bench/runner.py`) still allows exactly one
active run per FastAPI process — that contract is intact. Parallelism comes from
running **one independent worker process per scenario**, each with its own data
directory, never from sharing a runner.

## Worker contracts

Every link below (launcher, monitor, merge) relies on these four invariants. Change one
and you must change all three scripts plus this page in the same commit.

1. **One worker = one scenario = one data directory.**
   `JEVRAG_DATA_DIR=<repo>/backend/data_par/<scenario>` for *every* scenario, `squad`
   included. Each worker therefore owns its own `app.db`, Chroma index and fastembed
   cache, so two workers can never contend for a SQLite file.
   `backend/data_par/` is gitignored. All three scripts accept
   `JEVRAG_DATA_PAR_ROOT` / `--data-par` to point at a scratch root instead — use it for
   smoke runs so you never write into a previous full run's history.
2. **`RUN_ID=<uuid>` is the worker's machine-readable stdout line.**
   `backend/scripts/run_testbench.py` prints it with `flush=True` *before* loading local
   models; `backend/scripts/bench_resume.py` can only print it once its run row exists,
   i.e. *after* the ~17 s warm-up. Anything that needs the run id must therefore **poll**
   for the line (launcher default: 90 s, `RUN_ID_TIMEOUT`) — never sleep a fixed 2 s,
   which is the bug that left the M11 meta file with an empty run-id map.
3. **The DB is the source of truth for progress, not the log.**
   `bench_runs.status` (`running` / `completed` / `interrupted` /
   `window-budget-reached`) with `progress_done` / `progress_total` / `progress_stage`,
   plus the per-question rows in `bench_results`. Workers commit every triple
   atomically, so a killed worker loses at most one question. Logs are only a liveness
   and error-text aid; they are formatted for humans and are not a parse target.
4. **`backend/data_par/parallel_run_meta.json` describes the current launch.**
   Written by the launcher, read by the monitor and the merge script:

   ```json
   {
     "version": 1,
     "label": "my-run",
     "driver": "testbench",
     "arms": "base,gate-none",
     "scenarios": "squad,hotpotqa",
     "max_per_scenario": 0,
     "window_minutes": 100000,
     "num_workers": 2,
     "launched_at": "2026-09-30T14:35:00+05:30",
     "workers": [
       {"scenario": "squad", "run_id": "<uuid>", "pid": 1234,
        "data_dir": "<repo>/backend/data_par/squad",
        "log_file": "<repo>/backend/data_par/squad/bench.log"}
     ]
   }
   ```

## Sizing on this machine

Each worker is a full stack: jev-score subprocess (~1.5 GB RSS, CUDA on the RTX 2070 Super),
ONNX embedder + cross-encoder (CPU — ONNX Runtime CUDA does not work under WSL2, see
[setup-gpu.md](setup-gpu.md)), Chroma, and its own model warm-up. Measured footprint is
**~2.3 GB RAM per worker**, 12 cores, 15 GB total.

- Default `--max-parallel 5` (~11.5 GB) is the safe ceiling here; extra scenarios queue
  and start as slots free rather than oversubscribing RAM.
- Do not run this alongside the dev server, a browser, or a frontend rebuild.
- The GPU is *not* the constraint (embedder and reranker are on CPU), so more workers do
  scale wall-clock. The M11 full-power run finished 392 triples in ~2 h wall-clock
  across 5 workers versus ~5 h serial ([testbench-results-hgate.md](testbench-results-hgate.md)).
  Speedup is roughly 2.5–3× in practice, not 5× — the cloud LLM endpoint is the real
  bottleneck, not the box.

## Procedure

### 1. Preflight

```bash
cd /mnt/d/test_jev/jev-rag
test -d backend/.venv && test -f backend/.env && echo "venv+env OK"
bash scripts/probe_public_gateway.sh          # gateway + judge model reachable
```

`probe_public_gateway.sh` is a real gate, not a status printout: it exits **1** if any of the
three models or the judge `json_object` smoke fails, and exits 0 only on `STATUS: SUCCESS`.
It strips `\r` when reading `backend/.env`, because a CRLF env file (normal on a Windows
checkout) otherwise lands a CR inside the Authorization header and the URL and every call
fails. Every worker makes generator *and* judge calls, so a run launched past a failing probe
just produces error rows.

Models must already be built (`scripts/setup_local_models.sh`). Stop the dev server so it
does not hold a jev-score subprocess.

### 2. Launch

```bash
bash scripts/run_parallel_bench.sh --dry-run \
  --arms base,gate-none --scenarios squad,hotpotqa   # print the worker commands only
bash scripts/run_parallel_bench.sh \
  --arms base,gate-none,always-hard,oracle-gate \
  --scenarios squad,hotpotqa,triviaqa,wiki2,musique \
  --label hgate-par --max-parallel 5
```

Flags: `--driver testbench|resume` (default `testbench`), `--arms`, `--scenarios`,
`--label`, `--max-per-scenario N` (`0` = all), `--window-minutes N`, `--max-parallel N`
(default 5), `--resume scenario:run_id,...`, `--smoke` (resume driver only), `--dry-run`,
`-h`. Env fallbacks exist for every default (`ARMS`, `SCENARIOS`, `LABEL`, `MAX_PARALLEL`,
`RUN_ID_TIMEOUT`, `JEVRAG_DATA_PAR_ROOT`), flags win. The launcher detaches each worker
with `setsid nohup` so it survives the terminal, polls for `RUN_ID=`, then prints the
monitor and merge commands. `--dry-run` prints the exact worker command lines and exits
before creating any directory or file. A scenario whose run id never lands is reported
per scenario and makes the launcher exit non-zero — it never writes a half-populated
meta file silently.

Driver mapping — the launcher's job, and the reason one entrypoint covers both suites:

| `--driver` | worker | per-scenario args | resume arg |
| --- | --- | --- | --- |
| `testbench` | `backend/scripts/run_testbench.py` | `--arms --scenarios <sid> --max-per-scenario --window-minutes --label` | `--resume <run_id>` |
| `resume` | `backend/scripts/bench_resume.py` | `--scenarios <sid> --max-minutes --label` | `--run-id <run_id>` |

`--smoke` is passed through to the `resume` driver only.

### 3. Monitor

```bash
bash scripts/check_parallel_bench.sh          # human-readable
bash scripts/check_parallel_bench.sh --json   # for scripts/CI
tail -f backend/data_par/squad/bench.log      # error text for one worker
```

Exit codes: `0` every worker's run is `completed` · `1` at least one still running ·
`2` nothing running and no meta file to report on (also a usage error) ·
`3` finished-but-incomplete — a worker died or hit its window budget without reaching
`completed`, or the meta file is unreadable; read §4 before merging. A `running` DB row
whose pid is gone is exit 3, not 1 — that is the crash you must notice. Progress shows
`done/total` from the DB (`run_testbench.py` persists `progress_total` before the first
ingest, so the denominator is real from the first poll; `bench_results` row counts are shown
alongside as the hard ground truth).
**One intentional 3:** a `--driver resume --smoke` run stops after 2 questions and
`bench_resume.py` leaves its run row at `status='running'` with stage `smoke complete`, so the
monitor reports `dead_incomplete` / exit 3 for a smoke that finished exactly as asked. Read
`progress_stage` before believing the crash story — `smoke complete` or
`paused (resumable — deadline)` means the worker stopped on purpose.
Note: under `wsl -- bash -ic`, `$?` does not reliably carry a script's status — capture it
in-process if you are scripting around the monitor. Piping the launcher through `head` shows
141 (SIGPIPE), not its real status.

### 4. Resume if a window ends or a worker dies

Workers skip triples already present in their own DB, so resuming is idempotent — rerun
the same launcher command with `--window-minutes` for the time you have, or resume a
specific scenario:

```bash
bash scripts/run_parallel_bench.sh --scenarios musique --resume musique:<run_id> \
  --arms base,gate-none --window-minutes 60
```

A 0-byte `bench.log` means the worker died during startup (this is what happened to
musique's first launch in the M11 run) — relaunch that scenario alone.

### 5. Merge

```bash
cd backend
.venv/bin/python scripts/_merge_par_run.py --label "hgate-par (merged)"
```

No arguments needed when a meta file exists: it reads `workers[]` for each scenario's
`run_id` and `data_dir` (`--meta PATH` to point elsewhere, `--data-par ROOT`, `--out DB`
to write a scratch merged DB). Explicit overrides: `--run-ids scenario:uuid,...` and
`--data-dirs scenario:path,...` always beat the meta file; `--scenarios` selects
scenarios and `--arms` narrows rows by `bench_results.mode` (the arm lives in `mode`;
`traditional`/`hybrid` for resume-driver runs — an `--arms` value matching nothing warns
rather than silently merging wrong data).

Selection and output rules:

- One run wins per scenario: the `completed` run with the most rows for that scenario, so
  a later in-flight retry cannot win the tie-break. If no run reached `completed`, it
  falls back to the most-rows run of any status and prints a **PARTIAL** warning — merge
  anyway, but resume first if you want a full number.
- A scenario split across several resume runs is **not** unioned; finish it as one run.
- Result rows are deduplicated on (`scenario_id`, `question_id`, `mode`), preferring a row
  from a `completed` run, and every copied row gets a fresh id so source primary keys can
  never collide. Sources are opened read-only; only `--out` is written, and it refuses to
  overwrite a source DB or `backend/data/`.
- Output is a rebuilt merged DB with one unified `bench_runs` row (`summary` is NULL —
  that is why §6 uses `analyze_testbench.py`), `config.merged_from` / `merged_run_ids`
  recording provenance, and any partial-source problem surfaced on the run row.
- Exits: `0` merged · `2` a source DB is missing · `3` a source is unreadable ·
  `4` a scenario contributed zero rows. All of them abort *before* writing anything.

The command prints the merged run id on its own line — record it, it is what reports cite.
**A re-merge mints a brand-new unified run id** (the merged DB is rebuilt from scratch every
run, so idempotency is about *content*, not identity). Any id already cited in a results doc
or analysis command is orphaned by re-running the merge — the analyzer answers
`run <old-id> not found` and exits 1. Re-merge, then re-analyse with the id the merge just
printed; never capture the id before a planned re-merge.

### 6. Analyze and export

```bash
# public testbench runs
JEVRAG_DATA_DIR=backend/data_merged \
  .venv/bin/python scripts/analyze_testbench.py <merged-run-id> \
  --out ../docs/testbench-results-<label>.md
```

`export_bench_results.py` targets the *serial* internal-suite runs (it needs
`bench_runs.summary`, which the testbench driver never writes); for parallel runs use
`analyze_testbench.py` as above, and export the merged row's JSON by hand only if a
report needs it.

### 7. Cleanup

`backend/data_par/` and `backend/data_merged/` are disposable — deleting them never
touches `backend/data/`, which holds your documents and conversations. Keep
`parallel_run_meta.json` until the merged run id is recorded in a results doc.

## Failure modes worth knowing

| Symptom | Cause and fix |
| --- | --- |
| `run_ids`/`workers` empty in the meta file | worker died before printing `RUN_ID=`; see its `bench.log`, relaunch that scenario |
| `database is locked` | two processes sharing one `data_dir`; the launcher guard prevents it — check `--data-dirs` overrides |
| merge exits `MISSING: …` | a scenario DB was never created (worker died pre-ingest) or `--scenarios` names one that never ran |
| one `error` row per some question | accepted and kept visible, never silently dropped — a transient `APITimeoutError` is data (M11 kept 1 of 392) |
| monitor exits 3 | do not merge and call it a full run; resume first — unless `progress_stage` is `smoke complete` / `paused (resumable — deadline)`, which are deliberate stops (§3) |
| `analyze_testbench.py` says `run … not found` | the merged DB was rebuilt by a later `_merge_par_run.py` call, which mints a fresh unified run id each time — cite the id the **latest** merge printed |

## Related

- [benchmarking.md](benchmarking.md) — binding methodology, metrics, judge protocol
- [testbench-design.md](testbench-design.md) — arms and public scenarios
- root `AGENTS.md` §"Benchmarks may run with parallel workers" — the repo-wide permission
  and sizing rule this runbook implements
