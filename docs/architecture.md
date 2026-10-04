# Architecture

> **TL;DR**: Jev-RAG runs two RAG pipelines side by side over one shared retrieval stack:
> a **traditional** path (BM25 + dense → RRF → cross-encoder rerank → one cloud call) and a
> **hybrid** path that adds a local 0.8B decision model for three relative judgments — effort
> routing, best-of-2 selection, citation verification — plus a score-feature
> [escalation gate](glossary.md) that decides *after* retrieval whether a question needs the
> expensive path. Everything except the cloud LLM endpoint runs on-device.

Jev-RAG is a local-first hybrid [RAG](glossary.md) system: everything except the cloud LLM endpoint runs
on-device. It is currently the **v3** pipeline; the v1 and v2 pipeline shapes are kept as
history in [hybrid-design.md](hybrid-design.md), not described here.

```mermaid
flowchart LR
  UI["Next.js 16 UI<br/>chat · trace · documents · lab"] --> RW["/backend-api/*<br/>rewrite"] --> API["FastAPI :8000<br/><b>traditional</b> | <b>hybrid</b> pipelines"]
  ING["ingestion<br/>markitdown · chunk · embed"] --> RET
  API --> RET["retrieval<br/>BM25 ‖ dense → RRF k=60<br/>cross-encoder rerank → top-4"]
  API --> JEV["jev-score · llama.cpp<br/>Jev-style 0.8B GGUF Q4_K_M"]
  API --> DB[("ChromaDB vectors<br/>SQLite docs · traces")]
  API -->|"the only call that leaves"| LLM["Dashscope<br/>qwen3.7-plus"]

  classDef local fill:#0b1310,stroke:#10b981,color:#e4e4e7
  classDef edge fill:#0c1218,stroke:#0ea5e9,color:#e4e4e7
  classDef store fill:#111114,stroke:#3f3f46,color:#e4e4e7
  classDef cloud fill:#0f1115,stroke:#a1a1aa,color:#e4e4e7
  class UI,RW,API,ING,RET,JEV local
  class DB store
  class LLM cloud
```

If the backend is down, the Next.js `/api/ensure-backend` route re-spawns it detached
([`src/app/api/ensure-backend/route.ts`](../src/app/api/ensure-backend/route.ts)) —
that self-healing hop is left out of the diagram to keep the request path readable.

## Components

| Layer | Choice | Why |
| --- | --- | --- |
| Backend framework | FastAPI + Uvicorn | async SSE streaming, standard OpenAPI ecosystem |
| Parsing | markitdown | PDF/DOCX/XLSX/MD/CSV/HTML → text in one call |
| Chunking | langchain-text-splitters | battle-tested recursive splitting, contextual-prefix aware |
| Embeddings | fastembed (ONNX, CPU) `paraphrase-multilingual-MiniLM-L12-v2` | no torch, ~50 languages, 384-dim |
| Vector store | ChromaDB (embedded, persistent, cosine) | zero-ops local vectors |
| Lexical index | BM25 (rebuilt from Chroma contents, in-memory) | rescues lexical/entity lookups that dense misses |
| Reranker | cross-encoder (ONNX, CPU, batched pairs) | dominates 0.5B generative rerank on quality/$ |
| System One (decisions) | `jev-style` package + Jev-Style-0.8B-Decision-v3-GGUF (Q4_K_M, 0.53 GB) on llama.cpp via `jev-score` | open-source Jev-style typed calibrated decisions — v3 limited to relative judgments only |
| System Two (generation) | Dashscope OpenAI-compatible endpoint | qwen3.7-plus — the single generator |
| Relational store | SQLAlchemy 2 + SQLite | documents registry, conversations, messages + full pipeline traces |
| Frontend | Next.js 16 App Router, TS, Tailwind 4, shadcn/ui, zustand | modern standard stack |

## Data flow (v3 pipelines)

Both pipelines share the v3 retrieval stack; the hybrid adds a Jev-augmented agentic layer
only on questions that need it. See [rag-upgrade-2026.md](rag-upgrade-2026.md) for the
design rationale and [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md) for measured results.

### Shared retrieval stack (both arms)

```mermaid
sequenceDiagram
    participant User
    participant FastAPI
    participant BM25
    participant Dense
    participant RRF
    participant CrossEncoder

    User->>FastAPI: Query
    par Parallel retrieval
        FastAPI->>BM25: BM25 top-N
        FastAPI->>Dense: Dense top-N
    end
    BM25-->>RRF: Candidates
    Dense-->>RRF: Candidates
    RRF->>CrossEncoder: Fused candidates (k=60)
    CrossEncoder-->>FastAPI: Reranked top_k_use (4)
```

**Indexing pipeline:** markitdown → structure-aware split (headings, ~900/140 preserved) → contextual prefix ("doc title — section") into chunk text → [dense embed](glossary.md) (fastembed) into Chroma (cosine) → [BM25](glossary.md) index over the same chunks (rebuilt lazily from Chroma contents).

**Query pipeline:** [BM25](glossary.md) top-N ‖ dense top-N → [RRF](glossary.md) fusion (k=60) → [cross-encoder](glossary.md) rerank (ONNX, CPU, batched pairs) → top_k_use.

### Traditional v3 (= 2026 baseline)

```mermaid
sequenceDiagram
    participant User
    participant FastAPI
    participant Retrieval
    participant CloudLLM

    User->>FastAPI: Query
    FastAPI->>Retrieval: RRF retrieval
    Retrieval-->>FastAPI: Candidates
    FastAPI->>FastAPI: Cross-encoder rerank → top-4
    FastAPI->>CloudLLM: One call with context
    CloudLLM-->>FastAPI: Answer with citations
    FastAPI-->>User: Response (no local model, no gate)
```

RRF retrieval → cross-encoder rerank → top-4 → **one** cloud call → answer with citations.
No local LLM anywhere.

### Hybrid v3 (escalation design — the gate inversion)

```mermaid
sequenceDiagram
    participant User
    participant FastAPI
    participant Jev as Jev 0.8B (local)
    participant Retrieval
    participant Gate
    participant CloudLLM

    User->>FastAPI: Query
    par Concurrent, not sequential
        FastAPI->>Jev: Effort routing — chat vs doc
        FastAPI->>Retrieval: RRF retrieval (BM25 ‖ dense)
    end
    Retrieval-->>FastAPI: Candidates
    FastAPI->>FastAPI: Cross-encoder rerank → top-4
    FastAPI->>Gate: Top-1 rerank score vs θ (0.6)

    alt Easy path — top-1 ≥ θ
        Gate-->>FastAPI: pass
        FastAPI->>CloudLLM: One call with top-4
        CloudLLM-->>FastAPI: Answer with [n] citations
        FastAPI->>Jev: Citation verification per [n]
        Jev-->>FastAPI: supports / contradicts / says-nothing
    else Hard path — top-1 < θ
        Gate-->>FastAPI: escalate
        FastAPI->>CloudLLM: Decompose into sub-queries
        CloudLLM-->>FastAPI: Sub-queries
        FastAPI->>Retrieval: Per-sub-query RRF
        Retrieval-->>FastAPI: Candidates
        FastAPI->>FastAPI: Rerank
        Note over FastAPI,Jev: Passage battery — OFF by default
        FastAPI->>Gate: Second reading
        opt Second reading also fails
            FastAPI->>CloudLLM: Corrective retry — rewrite query, re-retrieve
            CloudLLM-->>FastAPI: Retry answer
        end
        par Concurrent
            FastAPI->>CloudLLM: Candidate A (thinking off)
            FastAPI->>CloudLLM: Candidate B (thinking on)
        end
        FastAPI->>Jev: Best-of-2 selection
        Jev-->>FastAPI: Selected candidate
        FastAPI->>Jev: Citation verification per [n]
        Jev-->>FastAPI: supports / contradicts / says-nothing
    end
    FastAPI->>FastAPI: Composite quality 0.4·asked + 0.4·supported + 0.2¬contradicts
    FastAPI-->>User: Streamed answer + citations + full trace
```

**Effort routing** ([Jev](glossary.md), concurrent with retrieval): decides chat vs doc, P≥0.9 fast path, validated 0.76–0.96 vs ≤0.17 separation.

**Easy path** ([escalation gate](glossary.md) passes: top-1 rerank score ≥ θ, calibrated on eval data): one cloud call → Jev citation verification → done.

**Hard path** (gate fails: score < θ): cloud decompose → per-sub-query RRF retrieval → rerank → optional passage battery (OFF by default) → CRAG corrective retry (1) → best-of-2 (Jev selects — relative judgment) → one cloud call → Jev citation verification → composite quality.

**Score-feature escalation gate.** The gate decides whether a question needs the
expensive hard path *after* cheap retrieval, not before. It reads the calibrated signals
available after retrieval and **escalates iff the top-1 cross-encoder score is below θ**
(shipped default 0.6, `app/config.py` `gate_score_threshold`). Four further features —
top1−top2 margin, top-k mean, count-above-floor, and the top-2 score itself — are
computed and shipped in the trace for inspection, but they do **not** enter the verdict.
θ is calibrated offline on labeled eval data (gold-in-top-4); that calibration is a
`backend/scripts/eval_retrieval.py` path, not a runtime one. This replaces the v2 absolute
sufficiency gate which asked the 0.8B model for a yes/no judgment — a task the calibration
literature and our own measurements showed it could not do reliably.

**Jev re-placement (evidence-driven).** v3 limits Jev to three relative judgments
where small models perform well: effort routing (chat vs doc), best-of-2 selection
(faithful vs planted candidate), and citation verification (per-citation supports/
contradicts/says_nothing). Pointwise rerank and absolute sufficiency gating moved
to cross-encoder and score-features respectively.

**Composite quality score** in code: 0.4·answers_request + 0.4·citations_supported +
0.2·¬contradicts_context; message + full trace persisted, every decision in the UI trace panel.

**Two hybrid branches the diagram above leaves out, because they are exits rather than
stages.** (1) Effort routing can return `no_retrieval` with P ≥ 0.9 — a chat-style question
that needs no passage at all — in which case the pipeline answers from one cloud call with
an explicit "no passages" context and returns, skipping rerank, gate and verification.
(2) If retrieval returns nothing, it answers the same way and returns. Both are in
`backend/app/rag/pipelines.py`; the trace panel shows them as a `routing` event with
`direct: true`.

## What runs where?

Jev-RAG is designed to run entirely on your local machine, with only the cloud LLM endpoint external. Here's the topology:

```mermaid
flowchart LR
  BR["your browser"] -->|"HTTP + SSE"| N["Next.js :3000<br/>/backend-api/* rewrite"]
  N --> F["FastAPI :8000"]
  F --> L["<b>on your machine</b><br/>ChromaDB · SQLite<br/>embedder · BM25 · cross-encoder<br/>jev-score (llama.cpp)"]
  F -->|"HTTPS — the only egress"| D["<b>off your machine</b><br/>Dashscope<br/>qwen3.7-plus"]

  classDef local fill:#0b1310,stroke:#10b981,color:#e4e4e7
  classDef cloud fill:#0f1115,stroke:#a1a1aa,color:#e4e4e7
  class BR,N,F,L local
  class D cloud
```

**On this system (Windows + WSL2):**
- The browser runs natively on Windows.
- Next.js, FastAPI, and all local models run inside **WSL2 Ubuntu-24.04** at `/mnt/d/test_jev/jev-rag`.
- The GPU (RTX 2070 Super) accelerates `jev-score` via llama.cpp CUDA, but the embedder and cross-encoder fall back to CPU (ONNX Runtime doesn't support WSL2 GPU passthrough — see [setup-gpu.md](setup-gpu.md)).

> **Note**: On native Linux or macOS, all components run directly on the host without WSL2. The GPU can accelerate all three local components if ONNX Runtime CUDA is configured.

## Process topology (sandbox)

- Next.js dev server is platform-managed; it proxies `/backend-api/*` to FastAPI and can
  re-spawn it (`/api/ensure-backend`), making the backend self-healing.
- `jev-score` runs as a persistent JSON-lines subprocess of the FastAPI process; the jev-style
  adapter serializes decisions on one worker thread.
