# Troubleshooting

This page is for the app that's **installed and misbehaving** — it won't start, uploads fail,
answers look wrong, the backend died. If you're still on a fresh machine and a setup script
failed, that's a different problem: go to
[setup.md — Troubleshooting](setup.md#troubleshooting), which owns the install-level table
(compiler missing, download stalls, PyPI mirrors). Don't duplicate it here.

Every entry is symptom → **Check** (which cause is it) → **Fix**. Commands are written for
Linux/macOS or WSL2 — run them from the repo root.

## It won't start

You open `http://localhost:3000` and the header keeps showing the spinner pill
"waking local models…", or `bash scripts/dev.sh` exits with an error.

**Check.** Where did the backend try to come up from? If the frontend spawned it itself
(the self-healing launcher in `src/app/api/ensure-backend/route.ts`), its output goes to
`logs/backend.log` at the repo root; if you ran `dev.sh`, the errors are in that terminal.
The launcher polls the backend's health endpoint for up to ~2.5 minutes (60 × 2.5 s) before
giving up, so "stuck" for a minute or two can be normal booting, not a hang. Read the log
and sort the cause:

- **First boot ever** — the backend loads its models eagerly at startup, and the first load
  downloads the ~225 MB embedding model into `backend/data/fastembed_cache/`. Slow is
  expected once.
- **`backend/.env` missing or key unfilled** — `dev.sh` copies the template for you, but the
  template ships `JEVRAG_DASHSCOPE_API_KEY=your-api-key-here`, and a placeholder key never
  appears as an error at boot; it appears later when every answer fails. Confirm with
  `bash scripts/probe_public_gateway.sh` — it exits 1 (with `FATAL: JEVRAG_DASHSCOPE_API_KEY
  not set` if the variable is empty, with failed model checks if it's a placeholder).
- **Missing venv or local models** — `dev.sh` auto-runs the setup scripts, and the
  `jev-score` compile alone takes 5–10 minutes on 2 cores. The spinner isn't a hang.
- **Anything else** — import errors, missing `bun`/`uv`, C++ compiler: that's install-level,
  take the log line to [setup.md — Troubleshooting](setup.md#troubleshooting).

**Fix.** For the first two, patience and a key respectively. For a wedged launcher you can
always start the backend in the foreground and read its errors directly:
`bash scripts/backend_service.sh`. Raise detail with `JEVRAG_LOG_LEVEL=DEBUG`
([configuration.md — Server and logging](configuration.md#server-and-logging)); backend
log lines are tagged with `jevrag.*` module names, which makes the useful section easy to
find. See [Collecting diagnostics](#collecting-diagnostics) before filing an issue.

## Hybrid mode says the local Jev engine is unavailable

A red box in the chat reads `Local Jev-style engine unavailable: …` — that exact string is
the error frame the hybrid pipeline emits when the local decision engine can't run
(`backend/app/rag/pipelines.py`, and the engine's own messages come from
`backend/app/llm/jev_engine.py`). Traditional mode still works; the app degrades rather
than crashing.

**Check.** Click the status pill (top-right) and look at the "Local Jev engine (System One)"
row — when it's down, it shows the engine's actual load error in red, and **Copy status
JSON** puts the whole thing (`jev.error`, paths, quant) on your clipboard. Read it:

- The error mentions the model dir, the GGUF file, or the scorer binary → path problem:
  `JEVRAG_JEV_MODEL_DIR` (default `./models/jev-style`) or an explicit
  `JEVRAG_JEV_SCORER` pointing at a file that doesn't exist. Leave `JEVRAG_JEV_SCORER` unset
  unless the runtime lookup fails ([configuration.md — Models](configuration.md#models)).
- The error is an OS-level failure or the engine was fine yesterday → the `jev-score`
  subprocess was likely killed (memory pressure; it needs roughly 1.5 GB RSS).
- `JEVRAG_JEV_ENABLED=false` in an old `.env` → the engine is off by request.

**Fix.** **Ask the question again first.** The engine reloads its subprocess on death and
retries the decision once inside the same call (`JevEngine._decide`), so a single OOM kill
usually shows you the red box and then never again. If it persists: check the paths above,
then rebuild the scorer with `bash scripts/setup_local_models.sh` (idempotent — finished
phases are skipped), and restart the backend. Never strip the auto-reload path out of
`jev_engine.py` — it's the recovery for this exact symptom.

## My `.env` change did nothing

You edited `backend/.env`, saved, and behavior didn't change.

**Check.** Settings are read **once at backend startup** and cached
([configuration.md — How settings work](configuration.md#how-settings-work)) — there is no
hot reload. Also confirm the variable name actually exists: unknown `JEVRAG_*` lines are
silently ignored, so a typo looks identical to "no effect". The backend's startup log prints
one line, `settings loaded: llm_default=… jev_dir=… data=…`, which shows what it really read.

**Fix.** Restart the backend (Ctrl-C in `dev.sh`, or kill the process if the frontend
spawned it — the UI will wake it again). Cross-check your line against
[.env.example](../backend/.env.example) or the variable tables in
[configuration.md](configuration.md).

## Uploads

The toast reads `N/M file(s) failed to index`, a document shows a red **error** chip, or the
error says `no extractable text found in the file`.

**Check.** Hover the red chip in the sidebar — you'll see the stored exception, which is one
of the backend's literal strings (`backend/app/api/routes.py` +
`backend/app/rag/ingestion.py`):

- `no extractable text found in the file` — the parser (markitdown) got zero text out of
  it. A scanned/image-only PDF is the usual case.
- `file exceeds 25 MB limit` — per-file cap of 25 MiB; the rest of the batch still indexed.
- `too many files (max 10 per request)` — a request-level rejection: **nothing** indexed.
- `unsupported file type '.X' — supported: …` — 11 extensions are accepted
  (`.pdf .docx .xlsx .md .txt .html .htm .csv .json .xml .log`); the dropzone hint
  under-advertises them ([usage.md — Add documents](usage.md#add-documents)).
- `empty file` — 0-byte upload.

**Fix.** For scanned PDFs: OCR them first or export the text layer, then re-upload — there's
no OCR in the app. For size/count limits: split the batch or the file. Failed documents are
listed with their error; delete the stub via its trash icon and re-upload the corrected file.
Note there is no bulk delete, and no reindex either — a document that indexed with wrong
chunking must be deleted and re-uploaded
([usage.md — Re-ingest after changing chunking or models](usage.md#re-ingest-after-changing-chunking-or-models)).

## Answers

**"Answers cite `bench-*.md` files that aren't mine."** After any Benchmark Lab run, chat
answers start citing benchmark fake-corpora documents.

**Check.** The lab re-ingests its scenario corpora — about 779 committed `bench-*.md`
documents — through the same ingestor into the same vector collection your chat searches,
and chat never filters by document set. Confirm: the sources list under the answer shows
filenames starting with `bench-`, and the status pill's indexed-document count has jumped
to a number you never uploaded.

**Fix.** Delete the `bench-*` documents (sidebar, one at a time — there's no bulk delete)
or reset the whole data directory as documented in
[setup.md — Day-2 operations](setup.md#day-2-operations) — that also wipes your real
documents, so re-upload them. To stop it recurring, run the lab against a separate
`JEVRAG_DATA_DIR`, or accept the warning printed in
[usage.md — Run the benchmark lab](usage.md#run-the-benchmark-lab).

**"Answers are vague, ungrounded, or say there's not enough context."** Retrieval answers
only from your indexed corpus — with zero ready documents the app tells you so instead of
inventing. **Check.** The status pill's ready-document count and the retrieved-passages section of the
answer's trace panel — together they show whether the evidence was missing or just ranked
low. **Fix:** upload the relevant files and re-ask; if retrieval ranked the right passage
low, the knobs are in
[configuration.md — Retrieval](configuration.md#retrieval). What each pipeline does with
context is documented in [usage.md — Read an answer](usage.md#read-an-answer).

## Answers are slow

Hybrid answers take tens of seconds and you want to know what's actually eating the time.

**Check.** Open the trace panel (**View trace**) and read the **Timings** section —
per-stage milliseconds, sorted by cost. What normally dominates, in the published v3
profile measured on a 2-core sandbox: cloud LLM streaming (~20 s of every answer), then
the local decisions — each Jev `decide()` call costs a second or two on CPU, and the hard
path stacks more of them (decompose, corrective retry, best-of-2 doubles the cloud
generation). Numbers: traditional p50 ≈ 20 s, hybrid p50 ≈ 41 s on the 2-core sandbox
([hybrid-design.md — Latency profile](hybrid-design.md)); the `base` arm of Layer-2 run
`36abefc6` on a 12-core workstation came in around 20 s p50
([testbench-results-layer2-full9.md](testbench-results-layer2-full9.md)). The escalation
gate keeps this machine-dependent: at the default threshold roughly 1-in-5 public-benchmark
questions took the multi-step hard path in the published run — the other ~80% answered on
the fast path. The embedder and cross-encoder are ONNX and run on **CPU** by default;
GPU acceleration is optional, and on WSL2 ONNX Runtime cannot use the GPU at all — it falls
back to CPU silently
([setup-gpu.md — WSL2 GPU Limitation](setup-gpu.md#wsl2-gpu-limitation)).

**Fix.** Latency-vs-rigor knobs live in
[configuration.md — Retrieval](configuration.md#retrieval) and
[Hybrid pipeline](configuration.md#hybrid-pipeline-and-escalation-gate) (fewer candidates,
citation verification off, threshold up). Don't delete Jev decision points to save seconds;
tune the documented knobs. If a specific answer took minutes rather than tens of seconds,
that's not slowness — see [The backend died](#the-backend-died) and collect diagnostics.

## Cost shows `—`

The footer of an answer shows `—` instead of a dollar estimate.

**Check.** The estimate comes from a hardcoded two-row price table in
`backend/app/config.py` — `qwen3.7-plus` and `qwen3.6-plus` only. For any other generator,
`estimate_cost_usd` returns nothing and the UI prints `—` (the status popover's
`llm_model_default` tells you which generator you're running). **`—` is a display gap, not
a free call** — the tokens were still spent.

**Fix.** Switch back to a priced model, or add your model's (input, output) USD-per-Mtok
prices to the table in `config.py` and restart. Full explanation in
[configuration.md — Cost display](configuration.md#cost-display).

## The backend died

Answers start erroring, the status pill goes red, and the UI briefly shows
"backend waking up… retrying".

**Check.** Most common cause is an OOM kill of the `jev-score` subprocess or the whole
backend under memory pressure (the engine alone wants ~1.5 GB RSS). Look in `logs/backend.log`
(or the `dev.sh` terminal) for the process going quiet mid-request, and on Linux check the
kernel log (`dmesg | tail`) for a "Killed process" line. Two side effects confirm a restart
happened: any benchmark run that was in flight is marked failed with a message starting
`run orphaned by backend restart` — that's the startup reaper in
`backend/app/main.py` doing bookkeeping, not data corruption — and per-question bench
results that were already committed survive.

**Fix.** Close memory-heavy neighbors, then just ask again: the frontend's launcher respawns
the backend and the engine auto-reloads its subprocess — that recovery path is load-bearing,
don't remove it. If OOM kills keep happening, trim the scorer's footprint with
`JEVRAG_JEV_SCORE_N_CTX` (default 8192) and the paired
`JEVRAG_JEV_SCORE_N_SEQ_MAX` / `_N_OUTPUTS_MAX`
([configuration.md — Memory and latency](configuration.md#memory-and-latency)) — going
lower risks context-truncation errors, and the heap-cap knob is documented as not usable.
During benchmark runs, don't build the frontend concurrently
([setup.md — Troubleshooting](setup.md#troubleshooting) has the matching install row).

## The frontend can't reach the backend

The UI loads (localhost:3000 answers) but every action errors, or the status pill says
unreachable while the backend terminal looks fine.

**Check.** From the same machine: `curl -s http://127.0.0.1:8000/api/system/health`. A JSON
reply means the backend is up and the problem is the proxy path; connection refused means
it's simply not running (see [It won't start](#it-wont-start) — and remember that response
proves nothing else, per [Collecting diagnostics](#collecting-diagnostics)).

**Fix.** The Next.js dev server rewrites `/backend-api/*` to `http://127.0.0.1:8000/api/*`
by default. If you moved the backend's port (`JEVRAG_PORT`), export
`JEVRAG_BACKEND_ORIGIN=http://127.0.0.1:<port>` for the frontend process and restart
`bun run dev` — the rewrite is read at dev-server startup. If you're calling the API from a
browser directly instead of through the rewrite, the origin must be listed in
`JEVRAG_FRONTEND_ORIGIN` (CORS is explicitly non-wildcard by design —
[configuration.md — Who can reach this](configuration.md#who-can-reach-this)).

## Can't reach it from another device

A phone or another laptop can't open the app, even though it works on this machine.

**Check.** By default this is intentional: the backend binds `127.0.0.1` only, so nothing
outside this machine can connect — that's the safe default, not a bug. Confirm in
`backend/.env` that `JEVRAG_HOST` is unset or `127.0.0.1`.

**Fix.** `JEVRAG_HOST=0.0.0.0` in `backend/.env` and restart is the deliberate opt-in —
but think first: **the app has no auth at all**, and binding outward hands every device on
your network full read/write over your documents, conversations, and the delete buttons.
You'd also add that device's UI origin to `JEVRAG_FRONTEND_ORIGIN` if the browser calls the
API directly. The trade-off is spelled out in
[configuration.md — Who can reach this](configuration.md#who-can-reach-this); don't do it
casually.

## Collecting diagnostics

When something is wrong, work this ladder — it goes from "is it alive" to "what exactly
broke", and it's the order that gets you the shortest issue report.

1. **`curl -s http://127.0.0.1:8000/api/system/health`** — says
   `{"status":"ok","service":"jev-rag-backend"}`. **Read this honestly: that response is a
   constant.** The handler returns it unconditionally
   (`backend/app/api/routes.py`, `/system/health`) — it checks no database, no model, no
   API key. It proves the Python process is listening, nothing more. It's the first rung
   only because "is the server even up" has to be answered first.
2. **`GET /api/system/status`** — the endpoint that actually reports component health, and
   the one to paste into an issue. It checks the cloud endpoint (reachability + model
   list), the Jev engine (`info()` — including the load-error string when it's down), the
   embedding model, the retrieval stack, the vector store and its chunk count,
   document/conversation totals, and the nine config values in effect. Fastest way to get
   it: the status pill popover → **Copy status JSON**. Without a live backend the same JSON
   still tells you what's unloaded (`"ok": false` rows).
3. **`bash scripts/probe_public_gateway.sh`** — the cloud gate: models list, one chat per
   model, judge JSON check. Treat `STATUS: SUCCESS` + exit 0 as the pass line; any `FAIL`
   exits 1 and means **do not start a benchmark run** past it.
4. **`cd backend && .venv/bin/python -m pytest tests -v`** — the hermetic suite (no models,
   no network). Failing here means the code, not your data or endpoint.
5. **A live smoke test** — upload a sample document from `scripts/test-assets/`, ask a
   Compare-mode question, and see which of the two columns breaks
   ([setup.md — Verify the installation](setup.md#verify-the-installation)).

Supporting detail: backend logs go to stdout under `dev.sh`, or `logs/backend.log` when the
frontend spawned it; the frontend dev log is `dev.log`
([usage.md — Check the logs](usage.md#check-the-logs)). The trace panel is **not copyable**
— there's no copy button anywhere in it — so screenshot it when reporting a pipeline
problem; for machine-readable trace data use
`GET /api/conversations/{id}/messages` ([api.md](api.md)).
