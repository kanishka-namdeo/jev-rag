# API reference

Base: FastAPI serves everything under **`/api/*`** (direct) and **`/backend-api/*`**
(what the Next.js rewrite proxies). The frontend always calls the latter with relative URLs.

## REST endpoints

| Method | Path | Body / params | Response |
| --- | --- | --- | --- |
| GET | `/system/health` | — | `{"status":"ok","service":"jev-rag-backend"}` |
| GET | `/system/status` | — | full status: dashscope (model list), jev engine, embeddings, vector store, documents, config |
| POST | `/documents` | multipart `files[]` (≤10 files, ≤25 MB each; pdf/docx/xlsx/txt/md/csv/html/json/xml/log) | `{"documents":[{id, filename, status, chunk_count, error?}]}` |
| GET | `/documents` | — | `{"documents":[…]}` |
| DELETE | `/documents/{id}` | — | `{"deleted": id}` (404 if unknown) |
| GET | `/conversations` | — | `{"conversations":[{id, title, message_count, …}]}` |
| GET | `/conversations/{id}/messages` | — | `{"messages":[… incl. full trace]}` |
| DELETE | `/conversations/{id}` | — | `{"deleted": id}` |

## POST `/chat` — SSE stream

Request JSON:

```json
{ "message": "…", "conversation_id": "uuid|null", "mode": "traditional|hybrid" }
```

Response: `text/event-stream`, each frame `data: {json}\n\n`. Heartbeat `ping` frames keep the
connection warm during long local-model calls.

### Event sequence

```
meta         {conversation_id, mode, assistant_message_id}
status       {stage: retrieving|jev-routing|jev-screening|jev-gating|jev-verifying|…, detail}
retrieval    {retrieved: [{rank, chunk_id, filename, similarity, jev_score?, snippet}]}
decision     {decision: JevDecision}            (hybrid; one per System-One call — up to 8 in v2)
rerank       {kept: [lite chunks, jev_score set]} (hybrid)
routing      {effort: no_retrieval|single_pass|multi_step, model, probabilities, confidence}
sources      {citations: [{index, chunk_id, doc_id, filename, similarity, rerank_score?, snippet}]}
llm_start    {model, system, context_sufficiency?, best_of?}
delta        {content}                            (many, streamed — or chunked after best-of-2 selection)
decision     {decision: citations|verification|addresses|composite} (hybrid, after stream)
done         {message_id, model, content, usage, cost_usd, timings, decisions, retrieved, citations,
             verification?, context_sufficiency?, effort, quality_score?, best_of?, retried?,
             rewritten_query?, citations_verified?}
error        {message}                            (terminal on failure)
ping         {}                                   (keepalive)
```

v2 decision records in order: `effort` (choice) → `decompose` (plan, multi_step only) →
`rerank` (noul × passages) → `battery` (3 nouls/passage) → `corrective` (rewrite, retry only) →
`sufficiency` (noul) → `best_of_2` (noul, hard path only) → `citations` (choice × emitted [n]) →
`verification` (noul) → `addresses` (noul) → `composite` (weighted score).

`JevDecision` shape:

```json
{
  "name": "effort|decompose|rerank|battery|corrective|sufficiency|best_of_2|citations|verification|addresses|composite",
  "label": "…", "kind": "noul|choice|plan|rewrite", "question": "…",
  "answer": "…", "probabilities": {"…": 0.0}, "confidence": 0.0,
  "latency_ms": 0.0, "usage": {}
}
```

### Trace persistence

Every assistant message row in SQLite stores the full trace (`retrieved`, `decisions`,
`citations`, `timings`, `verification`, `context_sufficiency`, `effort`, `quality_score`,
`best_of`, `retried`, `rewritten_query`, `citations_verified`) and is replayed by
`GET /conversations/{id}/messages`.

## Frontend proxy contract

- `next.config.ts` rewrites `/backend-api/:path*` → `http://127.0.0.1:8000/api/:path*`
  (override origin with `JEVRAG_BACKEND_ORIGIN`).
- `/api/ensure-backend` (Next.js route) re-spawns the FastAPI server when down — the backend is
  self-healing; the store also retries a failed chat stream once after re-ensuring.
