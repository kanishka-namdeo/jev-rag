# Jev-RAG — local-first hybrid RAG

Two retrieval-augmented QA pipelines over your own documents, in one interface:

| | **Traditional RAG** | **Hybrid RAG (Jev-style)** |
| --- | --- | --- |
| Retrieval | embedding similarity (top-k) | broad retrieval + **local Jev-style rerank** with calibrated P(relevant) per passage |
| Quality gate | — | **Jev sufficiency gate**: P(context actually answers the question) |
| Model choice | fixed (`qwen3.7-plus`) | **Jev routing** picks `qwen3.7-plus` (fast synthesis) vs `qwen3.6-plus` (deep reasoning) per query |
| Verification | — | **Jev groundedness check** on the final answer (shown as a badge) |
| Trace | retrieval + LLM stats | every decision with probabilities, latencies, tokens, estimated cost |

Everything except the cloud LLM endpoint runs **locally**: embeddings (ONNX CPU), vector store
(ChromaDB embedded), the Jev-style decision model (0.53 GB GGUF on llama.cpp), and storage
(SQLite). Answers are streamed with inline `[1]`-style citations linked to your sources.

> **What is "Jev"?** [Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) is
> TypeSafe AI's closed-weights "System One" decision model — it makes typed, calibrated
> decisions (never generates text). This project uses its open-source, locally-runnable
> equivalent: [Jev-Style-0.8B-Decision-v3](https://huggingface.co/chaoliangUNSW/Jev-Style-0.8B-Decision-v3-GGUF)
> (Apache-2.0) via the [jev-style](https://github.com/lawrence3699/jev-style) package.
> The cloud "System Two" is an OpenAI-compatible Dashscope endpoint. See
> [docs/hybrid-design.md](docs/hybrid-design.md) for the full rationale and measured decision
> patterns.

## Stack

FastAPI · ChromaDB · fastembed (ONNX) · jev-style + llama.cpp (`jev-score`) · markitdown ·
langchain-text-splitters · SQLAlchemy/SQLite · OpenAI SDK (Dashscope) · Next.js 16 ·
TypeScript · Tailwind CSS 4 · shadcn/ui · zustand

## Quickstart

```bash
# 1) backend config
cp backend/.env.example backend/.env    # then set JEVRAG_DASHSCOPE_API_KEY

# 2) local models: Jev-Style GGUF + llama.cpp build of the jev-score scorer (~10 min)
bash scripts/setup_local_models.sh

# 3) backend venv (uv)
bash scripts/setup_backend.sh

# 4) frontend deps + run everything
bun install
bash scripts/dev.sh                    # backend :8000 + frontend :3000
```

Open http://localhost:3000, upload documents in the sidebar, and ask questions in any of the
three modes (Traditional / Hybrid · Jev / Compare).

Tests: `cd backend && .venv/bin/python -m pytest tests -v` · Lint: `bun run lint`

## Configuration (`backend/.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `JEVRAG_DASHSCOPE_BASE_URL` | `https://coding-intl.dashscope.aliyuncs.com/v1` | OpenAI-compatible endpoint |
| `JEVRAG_DASHSCOPE_API_KEY` | — | your key (never commit) |
| `JEVRAG_LLM_MODEL_DEFAULT` | `qwen3.7-plus` | default System Two model |
| `JEVRAG_LLM_MODEL_REASONING` | `qwen3.6-plus` | deep-reasoning route |
| `JEVRAG_JEV_MODEL_DIR` | `./models/jev-style` | Jev-Style GGUF folder |
| `JEVRAG_JEV_QUANT` | `Q4_K_M` | GGUF quantization |
| `JEVRAG_JEV_SCORER` | `./models/jev-style/build/jev-score` | scorer binary |
| `JEVRAG_EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | fastembed model (must be in its supported list) |
| `JEVRAG_TOP_K_RETRIEVE` / `JEVRAG_TOP_K_USE` | `10` / `4` | candidates for rerank / passages given to the LLM |
| `JEVRAG_HYBRID_VERIFY_ANSWERS` | `true` | post-answer groundedness check |

## How the hybrid pipeline works

```
query ─▶ embed (local ONNX) ─▶ ChromaDB top-10
      ─▶ Jev rerank: one decide() call, calibrated P(relevant) per passage ─▶ keep top-4
      ─▶ Jev sufficiency (noul) + model routing (choice) in one decide() call
      ─▶ cloud LLM streams cited answer (thinking suppressed)
      ─▶ Jev verification (noul): P(answer fully supported by passages)
```

Every decision is streamed to the trace panel with probability bars, and persisted with the
message. Full protocol: [docs/api.md](docs/api.md).

## Repository layout

```
backend/          FastAPI app (pipelines, Jev engine, ingestion, storage, tests)
src/              Next.js frontend (chat, trace panel, documents, store)
scripts/          setup / build / run scripts (+ validated decision experiments)
docs/             architecture, hybrid design rationale, API protocol
AGENTS.md         DOX framework — binding rules for any AI agent working here
```

## Working on this repo (humans and agents)

This repo uses the [DOX](https://github.com/agent0ai/dox) AGENTS.md hierarchy: read the root
`AGENTS.md` (and the nearest child doc) before editing, and run a DOX pass after meaningful
changes. Project-wide contracts (local-first, popular-OSS-first, no secrets in git,
live-browser verification for UI work, green tests/lint, push at milestones) are binding for
any agent regardless of ad-hoc instructions — see `AGENTS.md → Project-Wide Contracts`.
