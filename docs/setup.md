# Setting up Jev-RAG on another system

> **TL;DR**: One-command setup: clone → copy `.env` → run setup scripts → `dev.sh`. Total time: ~15 min on a 2-core/4 GB machine with decent bandwidth, dominated by the llama.cpp compile.

This guide takes a **fresh machine** — a clean Linux/macOS/WSL2 box with nothing but a
shell, a C++ compiler and internet access — to a running Jev-RAG stack: both RAG
pipelines, the local [Jev](glossary.md)-style decision model, the streaming UI and the benchmark lab.

Everything on this page was re-validated on a wiped environment on 2026-09-28: the
setup scripts ran end-to-end from an empty state (venv → models → backend boot, 35/35
tests green) exactly as documented below, launched from a working directory *outside*
the repo. If it doesn't work like this for you, that's a bug — please open an issue.

Related guides, for after you're up and running:

| You want… | Go to |
| --- | --- |
| What the two pipelines do differently | [README](../README.md) · [hybrid design](hybrid-design.md) |
| System architecture & data flow | [architecture.md](architecture.md) |
| Reproducing the benchmark numbers | [benchmarking.md](benchmarking.md) · [setup → benchmarks](#running-the-benchmarks) |
| The REST/SSE wire protocol | [api.md](api.md) |

---

## Requirements

### Hardware

| Resource | Minimum | Comfortable | Why |
| --- | --- | --- | --- |
| CPU | 2 cores x86_64/arm64 | 4+ cores | llama.cpp compiles & runs the 0.8B decision model on CPU |
| RAM | 4 GB | 8 GB | `jev-score` needs ~1.2 GB RSS (with the shipped context/buffer trims); the full stack idles at ~2 GB |
| Disk | ~5 GB free | 8 GB | repo + `backend/.venv` (~1.5 GB) + GGUF (0.53 GB) + llama.cpp build (~2 GB) + embedding model cache (~0.3 GB) |

### Operating system

| OS | Status | Notes |
| --- | --- | --- |
| Linux (x86_64) | ✅ tested | Ubuntu/Debian-class distros; CI runs ubuntu-latest |
| macOS (arm64/x86_64) | ✅ should work | scripts avoid GNU-only coreutils (file sizes via `python3`); install prerequisites with `brew` |
| Windows | ➖ via WSL2 | run everything inside the WSL2 Linux filesystem (not `/mnt/c`) for build performance |
| Any POSIX with bash + Python 3.12 | ➖ best effort | `set -uo pipefail` POSIX bash required |

### Software prerequisites

| Tool | Version | Install (Debian/Ubuntu) | Install (macOS) | Used for |
| --- | --- | --- | --- | --- |
| [Python](https://www.python.org/) | 3.12 | `apt install python3.12` (or uv fetches it) | `brew install python@3.12` | backend venv, setup helpers |
| [uv](https://docs.astral.sh/uv/) | any recent | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `brew install uv` | fast venv + dependency install |
| [bun](https://bun.sh) | ≥ 1.1 | `curl -fsSL https://bun.sh/install \| bash` | `brew install oven-sh/bun/bun` | frontend deps + dev server |
| git | any | `apt install git` | `brew install git` | clone, llama.cpp source |
| curl | any | `apt install curl` | (present) | model downloads, health checks |
| C++ toolchain | g++ or clang++ | `apt install build-essential` | `xcode-select --install` | compile llama.cpp / `jev-score` |
| make | any | (included above) | `brew install make` | llama.cpp build |
| [cmake](https://cmake.org/) | ≥ 3.14 | `apt install cmake` | `brew install cmake` | llama.cpp build — *if missing, the setup script tries a pip bootstrap automatically* |

### Network access

The setup needs to reach:

- `huggingface.co` — the [Jev-Style GGUF model](https://huggingface.co/chaoliangUNSW/Jev-Style-0.8B-Decision-v3-GGUF) (0.53 GB, 529,296,864 bytes) and runtime files
- `github.com` — [llama.cpp](https://github.com/ggml-org/llama.cpp) source (shallow clone)
- `pypi.org` (or a mirror, see [troubleshooting](#troubleshooting)) — Python wheels via uv
- `registry.npmjs.org` equivalents via bun install
- your **OpenAI-compatible LLM endpoint** at runtime (e.g. Dashscope) — see step 2 below

Everything else — embeddings, vector store, decision model, storage — runs locally;
no other external services are contacted (local-first contract, `AGENTS.md`).

---

## Setup, step by step

The time budget is the single total stated at the top of this page; within it, the
llama.cpp compile in step 2 is the longest block. Every step is **idempotent** —
safe to re-run; finished phases are skipped.

### Step 0 — clone

```bash
git clone https://github.com/kanishka-namdeo/jev-rag.git
cd jev-rag
```

> **What you should see:** A new `jev-rag/` directory with `backend/`, `src/`, `scripts/`, `docs/` subdirectories.

### Step 1 — backend configuration

```bash
cp backend/.env.example backend/.env
# edit backend/.env:
#   JEVRAG_DASHSCOPE_API_KEY=<your key>          (required)
#   JEVRAG_DASHSCOPE_BASE_URL=<your endpoint>    (any OpenAI-compatible /v1)
```

`backend/.env` is gitignored — keys never enter git. All variables and their defaults
are documented in the file itself and in [configuration.md](configuration.md).

**Model choices:** `JEVRAG_LLM_MODEL_DEFAULT` is the generator used by both pipelines
(default `qwen3.7-plus`). `JEVRAG_BENCH_JUDGE_MODEL` is the benchmark judge
(default `kimi-k2.5`) — it is deliberately a *different model family* than the
generator to avoid self-preference bias; keep that separation if you swap either.

### Step 2 — local models (Jev GGUF + `jev-score` scorer)

```bash
bash scripts/setup_local_models.sh
```

> **What you should see:** `STATUS: SUCCESS` at the end, plus a list of `jev-score*` binaries (expect `models/jev-style/build/jev-score`). The GGUF download is 0.53 GB (529,296,864 bytes) and the llama.cpp compile is the longest step (~5–10 min on 2 cores).

What it does, in phases (each resumable):

1. toolchain check (g++/clang++ mandatory; cmake auto-bootstraps via pip if missing)
2. downloads the Jev-Style runtime files + `Q4_K_M` GGUF (529,296,864 bytes, size-verified, resume-capable)
3. patches the runtime for memory-trimmed llama.cpp flags (`JEV_SCORE_N_CTX=8192`, seq/output buffer trims — cuts ~1 GB RSS vs stock, verified bit-identical)
4. shallow-clones llama.cpp and builds `jev-score`
5. prints every `jev-score*` binary it can find — expect `models/jev-style/build/jev-score`

Look for `STATUS: SUCCESS` at the end. Network-restricted? See
[troubleshooting](#troubleshooting) for the `JEVRAG_PIP_INDEX_URL` mirror override.

### Step 3 — backend virtualenv

```bash
bash scripts/setup_backend.sh
```

> **What you should see:** `STATUS: SUCCESS — backend/.venv ready`. This creates `backend/.venv` (Python 3.12 via [uv](glossary.md)) and installs all dependencies (~1.5 GB).

Creates `backend/.venv` (Python 3.12 via uv) and installs `backend/requirements.txt`,
then sanity-imports fastapi/chromadb/fastembed/jev_style. Ends with
`STATUS: SUCCESS — backend/.venv ready`.

### Step 4 — frontend dependencies

```bash
bun install
```

> **What you should see:** `bun install` completes with a summary like `+ XXX packages` and a `node_modules/` directory created.

### Step 5 — run everything

```bash
bash scripts/dev.sh
```

> **What you should see:** Two log streams — Uvicorn running on `http://127.0.0.1:8000` and Next.js on `http://localhost:3000`. Open **http://localhost:3000** in your browser.

`dev.sh` is self-healing: it auto-runs steps 1–3 if their outputs are missing, starts
uvicorn on `:8000`, then the Next.js dev server on `:3000`. Open **http://localhost:3000**,
upload a document in the sidebar, and ask a question in any of the three modes
(Traditional / Hybrid · Jev / Compare). The backend binds loopback only by default;
sharing it on your LAN is a deliberate opt-in (`JEVRAG_HOST`) with real exposure —
see [configuration.md](configuration.md).

First boot notes:

- backend startup loads the GGUF eagerly — expect **~15 s** to healthy
- the embedding model (~225 MB, `paraphrase-multilingual-MiniLM-L12-v2`) downloads on
  first use into `backend/data/fastembed_cache/` — one-time
- answers via the hybrid pipeline take ~30 s on 2 cores (three local decision calls);
  see latency knobs in [hybrid-design.md](hybrid-design.md)

---

## Where paths resolve (portability contract)

Jev-RAG's backend is **working-directory independent**. `backend/app/config.py`
anchors every relative path in `backend/.env` to the repo root
(`REPO_ROOT = backend/app/config.py → three levels up`), and discovers `backend/.env`
by absolute location — not by the process CWD. Concretely:

| Setting | Value in `.env.example` | Resolves to |
| --- | --- | --- |
| `JEVRAG_DATA_DIR` | `./backend/data` | `<repo>/backend/data` (SQLite, ChromaDB, uploads) |
| `JEVRAG_JEV_MODEL_DIR` | `./models/jev-style` | `<repo>/models/jev-style` |
| `JEVRAG_JEV_SCORER` | `./models/jev-style/build/jev-score` | same, absolute |

So you can launch uvicorn from `backend/`, from the repo root, or from anywhere else
(`bash scripts/backend_service.sh` works from any CWD) and get identical behavior.
Absolute paths in `.env` always pass through untouched — useful for placing the GGUF
on a different disk. The same anchoring applies to the diagnostics scripts under
`scripts/` and `backend/scripts/` (they derive the repo root from `__file__`).

No script or tracked source file contains machine-specific absolute paths; all
mirrors/overrides are opt-in environment variables. This is enforced by the repo's
agent contract (`AGENTS.md → Debuggable by default`) and CI.

---

## Verify the installation

Run these after setup; all should pass on a healthy install.

```bash
# 1) backend health (from any directory)
curl -s http://127.0.0.1:8000/api/system/health
#   -> {"status":"ok","service":"jev-rag-backend"}

# 2) endpoint reachability + model list (reads backend/.env; no hardcoded keys)
bash scripts/probe_public_gateway.sh
#   -> "OK /models: N model(s) served", then "OK qwen3.7-plus: OK-qwen3.7-plus",
#      "OK qwen3.6-plus: …", "OK kimi-k2.5: …", "OK judge json_object parses as a dict",
#      then "STATUS: SUCCESS" and exit 0. Any FAIL line exits 1 — do not start a
#      benchmark run past it.

# 3) hermetic test suite (no models, no network — same as CI)
cd backend && .venv/bin/python -m pytest tests -v    # 158 passed

# 4) frontend lint
cd .. && bun run lint                                # no output = clean
```

Then one **end-to-end smoke**: in the UI, upload any of the sample documents under
`scripts/test-assets/`, ask a question in Compare mode, and confirm both columns
answer with citations and the hybrid shows its Jev decision trace.

Day 2: how to use the app is in [usage.md](usage.md); every knob is in
[configuration.md](configuration.md); when something is wrong,
[troubleshooting.md](troubleshooting.md).

---

## Running the benchmarks

The Benchmark Lab (UI **Benchmarks** tab) ships with the full scenario suite **in the
repo** — no downloads needed:

- 6 internal scenarios (26 documents / 48 QA pairs) — distractor, policy, multilingual, abstention stress modes
- 5 popular public benchmarks — SQuAD v1.1, HotpotQA, TriviaQA, 2WikiMultiHopQA,
  MuSiQue (98 questions; corpora + manifest are committed under
  `backend/app/bench/corpora/`, so a fresh clone can run them immediately)

A full two-arm run over all scenarios is ~2–4 h on 2 cores and a few cents of endpoint
spend; a single-scenario smoke takes minutes. Methodology (independent judge,
position-swapped pairwise, canary self-test) is binding and documented in
[benchmarking.md](benchmarking.md).

**Rebuilding public scenarios from raw data (optional).** The committed corpora were
sampled (seed 42, full provenance in `backend/app/bench/corpora/public_benchmarks.json`)
from raw dataset files that are *not* in git. To re-derive or extend them, download the
parquets listed in the manifest's `provenance` (~280 MB total) into
`backend/data/public_bench/raw/`, then:

```bash
cd backend && .venv/bin/python scripts/build_public_scenarios.py [--force]
```

Without `--force` it appends only missing benchmarks and leaves existing ones
byte-identical; with `--force` it rebuilds everything from the raw files.

---

## Day-2 operations

| Task | How |
| --- | --- |
| Stop the stack | `Ctrl-C` in the `dev.sh` terminal (both children are trapped) |
| Backend only, any CWD | `bash scripts/backend_service.sh` |
| Logs | backend logs to stdout; frontend dev log at `dev.log` (gitignored) |
| Reset all data | `rm -rf backend/data` (SQLite + ChromaDB + uploads + caches — recreates on boot) |
| Reset models | `rm -rf models vendor`, re-run `scripts/setup_local_models.sh` |
| Upgrade | `git pull`, re-run steps 2–3 (idempotent), refresh `backend/.env` against `.env.example` if new vars appeared |
| Uninstall | delete the clone — nothing is installed outside it (`~/.cache`-style caches land in `backend/data/`) |

Ports: frontend `:3000`, backend `:8000` (the frontend proxies `/backend-api/*` →
`127.0.0.1:8000`; override with `JEVRAG_BACKEND_ORIGIN`). The root `Caddyfile` is a
sandbox preview helper, not needed for local use. For a production-ish single-port
deployment, `bun run build` produces a standalone Next.js server.

---

## Troubleshooting

| Symptom | Cause → fix |
| --- | --- |
| `cmake MISSING` and pip bootstrap fails | Install via OS: `apt install cmake` / `brew install cmake`; re-run step 2 (idempotent) |
| `FATAL: no C++ compiler (g++)` | Debian/Ubuntu: `apt install build-essential`; macOS: `xcode-select --install` |
| PyPI timeouts / slow wheels | Point uv at a mirror: `UV_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple/ bash scripts/setup_backend.sh`; the model-setup bootstrap honors `JEVRAG_PIP_INDEX_URL` the same way |
| GGUF download stalls | The script resumes (`curl -C -`, size-verified at 529,296,864 bytes) — just re-run step 2 |
| `FATAL: runtime constant block not found — upstream changed` | The upstream Jev-Style runtime file changed shape; port the two memory patches in `scripts/setup_local_models.sh` (phases 3b/3c) to the new anchors |
| Backend OOM-killed during hybrid queries / long bench runs | Close memory-heavy neighbors first (~1.2 GB RSS for `jev-score` is expected); lower `JEVRAG_JEV_SCORE_N_CTX` (default 8192) in `backend/.env`; during bench runs don't run the frontend build concurrently |
| `probe_public_gateway.sh`: `FATAL: JEVRAG_DASHSCOPE_API_KEY not set` | Set it in `backend/.env` or export it — the script never hardcodes keys |
| Endpoint 401/404 | Check `JEVRAG_DASHSCOPE_BASE_URL` (must be the `/v1` base) and the key; confirm with `bash scripts/probe_public_gateway.sh` |
| `backend/.env` edits don't take effect | Restart the backend (settings are read once at startup) |
| Frontend can't reach backend | Backend must be on `:8000`, or set `JEVRAG_BACKEND_ORIGIN` for the Next.js rewrite; health: `curl 127.0.0.1:8000/api/system/health` |
| First document upload is slow | One-time embedding-model download (~225 MB) into `backend/data/fastembed_cache/` |
| macOS: scripts complain about `stat`/arrays | Fixed in the current scripts (size checks use `python3`); ensure you're on the latest `main` |

This table is the install-level reference; the full symptom-ordered guide is
[troubleshooting.md](troubleshooting.md). If nothing helps, the backend log names its
module loggers (`jevrag.*`) — include the relevant section in any issue.

---

## What is guaranteed portable

- **No machine-specific absolute paths** in tracked scripts or sources (repo-root
  anchoring throughout; mirrors are opt-in env vars).
- **Idempotent setup** — every phase checks its own output before working; re-running
  after a failure never discards progress.
- **CWD-independent launches** — uvicorn, diagnostics and ops scripts resolve the repo
  from their own file location.
- **Secrets stay out of git** — `backend/.env` is gitignored; the endpoint probe reads
  credentials from it at runtime. (If you ever find a key committed by accident,
  rotate it — history retains it.)
- **Hermetic CI** — `.github/workflows/ci.yml` installs and tests exactly what this
  guide installs, on every push to `main`.
