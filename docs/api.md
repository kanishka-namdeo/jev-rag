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
status       {stage: retrieving|jev-reranking|jev-routing|jev-verifying|…, detail}
retrieval    {retrieved: [{rank, chunk_id, filename, similarity, jev_score?, snippet}]}
decision     {decision: JevDecision}            (hybrid; one per System-One call)
rerank       {kept: [lite chunks, jev_score set]} (hybrid)
routing      {model, probabilities, confidence}   (hybrid)
sources      {citations: [{index, chunk_id, doc_id, filename, similarity, rerank_score?, snippet}]}
llm_start    {model, system, context_sufficiency?}
delta        {content}                            (many, streamed)
decision     {decision: verification}             (hybrid, after stream)
done         {message_id, model, content, usage, cost_usd, timings, decisions, retrieved, citations, verification?, context_sufficiency?}
error        {message}                            (terminal on failure)
ping         {}                                   (keepalive)
```

`JevDecision` shape:

```json
{
  "name": "rerank|sufficiency|routing|verification",
  "label": "…", "kind": "noul|choice", "question": "…",
  "answer": "…", "probabilities": {"…": 0.0}, "confidence": 0.0,
  "latency_ms": 0.0, "usage": {}
}
```

### Trace persistence

Every assistant message row in SQLite stores the full trace (`retrieved`, `decisions`,
`citations`, `timings`, `verification`, `context_sufficiency`) and is replayed by
`GET /conversations/{id}/messages`.

## Frontend proxy contract

- `next.config.ts` rewrites `/backend-api/:path*` → `http://127.0.0.1:8000/api/:path*`
  (override origin with `JEVRAG_BACKEND_ORIGIN`).
- `/api/ensure-backend` (Next.js route) re-spawns the FastAPI server when down — the backend is
  self-healing; the store also retries a failed chat stream once after re-ensuring.
