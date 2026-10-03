# Usage

This is the day-to-day page: what you can click and what actually happens. It assumes the app
is already running — install is [setup.md](setup.md), and every environment variable, default
and trade-off lives in [configuration.md](configuration.md). The wire protocol (SSE events,
endpoints) is [api.md](api.md).

You open the UI at `http://localhost:3000`. By default the backend binds `127.0.0.1` and CORS
only accepts the frontend origin, so nobody else on your network can reach the app — it has no
auth at all. To deliberately share an instance, see
[configuration.md — Who can reach this](configuration.md#who-can-reach-this).

Everything except the final cloud LLM call runs on your machine, and there is **one shared
knowledge base**: every chat retrieves from all of your ready documents. The UI has no
per-document or per-chat scoping — you cannot pick a subset of files for a question.

## Add documents

In the sidebar, under **Knowledge base**, drop files onto the dashed box or click it to pick
them. What's accepted, straight from the code:

- **11 extensions**: `.pdf .docx .xlsx .md .txt .html .htm .csv .json .xml .log`. The small
  hint under the dropzone advertises only 7 (PDF · DOCX · XLSX · TXT · MD · CSV · HTML) and
  silently omits `.htm`, `.json`, `.xml` and `.log` — the hint is stale, not a limit. The file
  picker and the backend accept all eleven.
- **25 MiB per file, 10 files per request.** A file over the size limit comes back as its own
  per-file error and the rest still index; sending more than 10 files in one drop fails the
  whole upload with "too many files (max 10 per request)". There is no cap on the total corpus.
- Empty files and unsupported extensions are also per-file errors, never request failures.

Each uploaded file shows a spinner while **processing**, then either its chunk count
(`12 ch` — hover it for the file size) or a red **error** chip. Hover the error chip to read
the stored exception — that's where you'll see messages like
`no extractable text found in the file` (a scanned PDF with no text layer lands here).

Originals are stored under `<data_dir>/uploads/<uuid>.<ext>` (by default
`backend/data/uploads/`); your human-readable filename lives only in the SQLite database, which
is why deletion is per-file via the trash icon — there is no bulk delete.

To remove a document's chunks from the index, delete the document; to start clean, the
documented reset is `rm -rf backend/data`
([setup.md — Day-2 operations](setup.md#day-2-operations)).

## Re-ingest after changing chunking or models

**There is no reindex.** Chunking and embedding happen once, at upload time. If you change
`JEVRAG_CHUNK_SIZE`, `JEVRAG_CHUNK_OVERLAP` or the embedding model
([configuration.md — Retrieval](configuration.md#retrieval),
[Model swaps](configuration.md#model-swaps)), every already-ingested document keeps its old
chunks. The only fix is to delete and re-upload the affected documents (or reset the whole
data directory). Restarting the backend alone changes nothing for stored vectors.

## Ask a question

Type in the composer at the bottom and press **Enter** to send; **Shift+Enter** inserts a
newline. The default mode is Traditional.

- A message must be **1–8000 characters**. Send more and the backend rejects it with HTTP 422;
  the red box that appears reads `Error: [object Object]`, not the validation detail — see
  [Known gaps](#known-gaps).
- Follow-ups work: the last **8 messages** of the current conversation are replayed to the
  model as history. Older turns are not — the model genuinely forgets them.
- Conversations are titled automatically from your first question and can't be renamed. The
  History list shows the **100 newest** conversations with no pagination.
- While an answer streams, the mode tabs, the composer and history items all lock, and you
  **cannot stop the stream**. Wait for it to finish.
- With zero ready documents the empty state tells you to upload first; answers are grounded
  only in your files.

## Choose a mode

The header tabs pick the pipeline per question:

- **Traditional** — hybrid retrieval (BM25 + dense fused with RRF), cross-encoder rerank, then
  one cloud LLM call writes the cited answer. No local model does any reasoning here.
- **Hybrid · Jev** — everything Traditional does, plus the local System One: effort routing,
  a score-feature escalation gate that decides easy vs hard path (the calibrated top-1 rerank
  score against a threshold — the default lives in
  [configuration.md — Hybrid pipeline and escalation gate](configuration.md#hybrid-pipeline-and-escalation-gate)),
  and on the hard path sub-question decomposition,
  corrective query rewrite and retry, best-of-2 candidate generation with Jev selection, and
  batched citation verification that produces a composite quality score. Hybrid needs the
  local `jev-score` engine; if it's down you'll see "Local Jev-style engine unavailable" as a
  red box (it usually self-recovers — see [Check the logs](#check-the-logs)).
- **Compare** — not a third pipeline. Your browser fires **two concurrent runs** (Traditional
  and Hybrid) on the same question and renders them side by side. Both answers are persisted
  as separate assistant messages in the conversation, so they count toward the 8-message
  history window.

Start with Traditional for speed; use Hybrid when grounding quality matters more than latency,
and Compare when you want to see what System One adds on a specific question.

## Read an answer

An answer bubble is markdown with inline citations. What the affordances mean:

- `[1]` chips inside the prose are **clickable** — clicking one opens the trace panel for that
  message. `[1][3]` and `[1, 2]` forms are also recognised.
- Header chips: the cloud **model**, an **effort** chip on hybrid runs reading
  `no retrieval` | `single pass` | `multi-step`, and a `context 0.62` sufficiency chip
  (hybrid).
- Footer badges (both hybrid-only — traditional answers carry neither):
  - **quality NN%** — composite score,
    `0.4 · answers_request + 0.4 · citations_supported + 0.2 · no_contradiction`
    (green ≥ 80%, amber ≥ 50%).
  - **grounded NN%** — Jev P(answer supported by context); green ≥ 70%, amber ≥ 40%, red below.
- Also in the footer: `best-of-2 a 0.83 · b 0.61` when candidates were compared, a
  `corrective retry` marker when the query was rewritten after a failed sufficiency check,
  latency in seconds, `prompt→completion tok`, estimated cloud cost, and a source count.
- The **escalation decision itself is not in the bubble**. It's the trace card "Escalation gate
  (score features)", carrying `top1`, `top2`, `margin`, `mean`, `above_floor` and the threshold
  it was compared against.

There is **no copy-answer button** and no export of a conversation — you can select and copy
the rendered text from the browser, that's it.

![Chat answer with a pipeline trace panel open beside it](assets/img/trace-panel.png)

## Read the trace

Every answer with a pipeline trace has a **View trace** button in its footer; citation chips
open the same panel, and on narrower windows a header activity icon opens it as a sheet. The
panel shows up to six sections — some appear only when the run produced them:

1. **System One · Jev-style decisions** — one card per local decision (effort routing, rerank,
   gate, decomposition, best-of-2 selection, citation checks) with its answer, probability bars
   and latency.
2. **Best-of-2 candidates** — only when both candidates were generated (hard path).
3. **Retrieved passages** — candidates with similarity and (in hybrid) Jev relevance scores.
4. **Cited sources** — only the passages the generator actually referenced.
5. **System Two · generation** — model, latency, tokens, estimated cost.
6. **Timings** — per-stage milliseconds, sorted by cost.

Honest limitation: **the trace is not copyable**. There's no copy button on any of it, and the
only clipboard action in the whole app is **Copy status JSON** in the status pill's popover.
For machine-readable trace data, use `GET /api/conversations/{id}/messages` — every message's
trace is persisted
([api.md](api.md)).

## Run the benchmark lab

> **Warning — a lab run writes into your own knowledge base.** Each run (re-)ingests its
> benchmark corpora — ~779 committed `bench-*.md` files — through the same ingestor, into the
> same Chroma collection your chat searches, and chat requests never filter by document set.
> After any run, subsequent answers may cite benchmark fake-corpora documents as your files.
> If your real corpus matters, run the lab with a separate `JEVRAG_DATA_DIR`
> ([configuration.md — Server and logging](configuration.md#server-and-logging)), or delete
> `backend/data` afterwards ([setup.md — Day-2 operations](setup.md#day-2-operations)).

If that's fine (or you've isolated the data dir): click **Benchmarks** in the header, tick
scenario cards (or **Select all**), then **Run benchmark (N)**.

There are **11 shipped scenarios**:

| Group | Scenarios | Questions |
| --- | --- | --- |
| Internal (synthetic corpora) | `techdocs` `finance` `policy` `distractor` `multilingual` `outofscope` | 6 × 8 = 48 |
| Public benchmarks | `squad` (25) `hotpotqa` (25) `triviaqa` (16) `wiki2` (16) `musique` (16) | 98 |

All corpora are committed in the repo — no downloads, no dataset keys. Each question runs both
arms (Traditional and Hybrid) through the production pipelines, then an independent LLM judge
scores them. That means **real cloud cost** proportional to questions × 2 arms + judge calls.

Only one run at a time per backend process: starting a second while one is active gives a
409 "a benchmark run is already in progress". Progress shows as `done/total` questions with the
current stage; results persist per question, so killing the backend leaves a partial run you
can still inspect.

The dashboard, per completed (or live) run:

- Headline cards for the two arms: **Correctness (judge)**, **Faithfulness (judge)**, **Hit@4**,
  **MRR@10**, **Latency p50** (pipeline only, judge excluded) and **Cost / query** (cloud LLM
  generation).
- Per-scenario bar charts, pairwise win rates, gate analysis and abstention panels.
- A per-question table with drill-down: answer, reference, judge reasoning, retrieved files,
  timings, sufficiency and verification scores.

Deleting a run is offered **only on completed runs** — there's no cancel button in the UI even
though the backend supports cancellation. Methodology and metric definitions are binding in
[benchmarking.md](benchmarking.md); CLI and parallel-worker runs are
[setup.md — Running the benchmarks](setup.md#running-the-benchmarks) and
[parallel-bench-runbook.md](parallel-bench-runbook.md).

![Benchmark lab with scenario cards and run controls](assets/img/bench-lab.png)

## Check the logs

- The backend logs to its **stdout** (what you see when you run `scripts/dev.sh`); raise
  `JEVRAG_LOG_LEVEL` for detail ([configuration.md — Server and logging](configuration.md#server-and-logging)).
- When the frontend's self-healing launcher spawns the backend itself, its output goes to
  `logs/backend.log`.
- The frontend dev server is piped to `dev.log` at the repo root by `bun run dev` (gitignored).
- A red box saying the **Jev engine is unavailable** usually resolves itself: the engine
  reloads its subprocess on death and retries the decision, and a hybrid run retries once
  more at the pipeline level. Only if it persists is something actually wrong.

## Known gaps

These are real today — no euphemisms:

- **You cannot stop a running stream.** The send button swaps to a stop (square) glyph while
  streaming, but it's disabled and unwired — clicking it does nothing. Mode tabs, the composer
  and history clicks all lock until the answer completes.
- **An over-8000-character message is opaque.** The 422 carries a real validation detail, but
  the client stringifies it into nothing — the red box reads `Error: [object Object]`. The
  store's generic self-heal path can also re-fire the same doomed request once internally;
  that's an implementation detail, not something you're meant to watch. Stay under
  8000 characters.
- The dropzone hint advertises 7 formats; 11 are accepted (see [Add documents](#add-documents)).
- **No per-document scoping.** Every question searches your whole corpus — you can't limit one
  to a subset of files.
- **No copy-answer button**, and the trace panel isn't copyable. The only clipboard action in
  the app is "Copy status JSON" in the status popover.
- No export of benchmark results from the UI — that's CLI-only
  (`backend/scripts/export_bench_results.py`).
- No bulk delete: documents and conversations delete one at a time.
- No document preview — you can't open or inspect an uploaded file in the app, only delete it.
- No conversation rename, no conversation search, and history is capped at the 100 newest
  conversations with no pagination.
- No settings screen: every knob is `backend/.env`
  ([configuration.md](configuration.md)), then restart.
- No in-app cancel for benchmark runs (delete appears only after completion).
- No reindex: retrieval-related changes require re-uploading everything
  ([above](#re-ingest-after-changing-chunking-or-models)).
