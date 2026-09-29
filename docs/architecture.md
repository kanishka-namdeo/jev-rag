# Architecture

Jev-RAG is a local-first hybrid RAG system: everything except the cloud LLM endpoint runs
on-device.

```mermaid
flowchart LR
  subgraph Browser
    UI[Next.js 16 UI<br/>chat · trace · documents]
  end
  subgraph NextServer[Next.js server :3000]
    RW[/backend-api rewrite/]
    ENS[ensure-backend route<br/>self-healing launcher]
  end
  subgraph FastAPI[FastAPI :8000]
    CHAT[chat pipelines]
    ING[ingestion]
    DB[(SQLite<br/>docs · conversations · traces)]
    VS[(ChromaDB<br/>embedded vectors)]
    EMB[fastembed ONNX<br/>multilingual MiniLM-L12]
    BM25[BM25 lexical index<br/>rebuilt from Chroma]
    CE[cross-encoder rerank<br/>ONNX CPU]
    JEVL[jev-style 0.8B GGUF<br/>+ jev-score / llama.cpp]
    LLM[Dashscope endpoint<br/>qwen3.7-plus · qwen3.6-plus]
  end

  UI --> RW --> CHAT
  UI --> ENS
  ENS -.spawns.-> FastAPI
  CHAT --> EMB --> VS
  CHAT --> BM25
  CHAT --> CE
  CHAT --> JEVL
  CHAT --> LLM
  ING --> EMB --> VS
  ING --> DB
  CHAT --> DB
```

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

```
INDEX   markitdown → structure-aware split (headings, ~900/140 preserved)
        → contextual prefix ("doc title — section") into chunk text
        → dense embed (fastembed) into Chroma (cosine)
        → BM25 index over the same chunks (rebuilt lazily from Chroma contents)
QUERY   BM25 top-N ‖ dense top-N → RRF fusion (k=60)
        → cross-encoder rerank (ONNX, CPU, batched pairs) → top_k_use
```

### Traditional v3 (= 2026 baseline)

RRF retrieval → cross-encoder rerank → top-4 → **one** cloud call → answer with citations.
No local LLM anywhere.

### Hybrid v3 (escalation design — the gate inversion)

```
effort_routing (jev, concurrent with retrieval — only decides chat vs doc,
                P≥0.9 fast path, validated 0.76–0.96 vs ≤0.17 separation)
   ‖ retrieval (RRF) → cross-encoder rerank
EASY PATH  (gate passes: top-1 rerank score ≥ θ, calibrated on eval data)
           → one cloud call → jev citation verification → done
HARD PATH  (gate fails: score < θ)
           → cloud decompose → per-sub-query RRF retrieval → rerank
           → optional passage battery (OFF by default)
           → CRAG corrective retry (1)
           → best-of-2 (jev selects — relative judgment) → one cloud call
           → jev citation verification → composite quality
```

**Score-feature escalation gate.** The gate decides whether a question needs the
expensive hard path *after* cheap retrieval, not before. It uses calibrated signals
available after retrieval: top-1 cross-encoder score (primary), top1−top2 margin,
top-k mean, count-above-floor. Threshold θ is calibrated on labeled eval data
(gold-in-top-4) using Youden J. This replaces the v2 absolute sufficiency gate
which asked the 0.8B model for a yes/no judgment — a task the calibration literature
and our own measurements showed it could not do reliably.

**Jev re-placement (evidence-driven).** v3 limits Jev to three relative judgments
where small models perform well: effort routing (chat vs doc), best-of-2 selection
(faithful vs planted candidate), and citation verification (per-citation supports/
contradicts/says_nothing). Pointwise rerank and absolute sufficiency gating moved
to cross-encoder and score-features respectively.

**Composite quality score** in code: 0.4·answers_request + 0.4·citations_supported +
0.2·¬contradicts_context; message + full trace persisted, every decision in the UI trace panel.

## Process topology (sandbox)

- Next.js dev server is platform-managed; it proxies `/backend-api/*` to FastAPI and can
  re-spawn it (`/api/ensure-backend`), making the backend self-healing.
- `jev-score` runs as a persistent JSON-lines subprocess of the FastAPI process; the jev-style
  adapter serializes decisions on one worker thread.
