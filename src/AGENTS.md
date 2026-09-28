# Frontend DOX (src/)

## Purpose

- Own the Next.js 16 App Router UI: chat with SSE streaming, mode selection (traditional /
  hybrid / compare), document management sidebar, Jev decision trace panel, system status,
  and the Benchmarks lab (scenario selection, live run progress, results dashboard).

## Ownership

- `app/page.tsx` — page shell: header, view switch (Chat | Benchmarks), sidebar, chat, trace panel
- `app/layout.tsx` — fonts, metadata, theme provider, toasters
- `app/api/ensure-backend/route.ts` — self-healing backend launcher (spawns uvicorn detached)
- `lib/jevrag/api.ts` — backend client; ALL backend calls go through `/backend-api/*` (Next rewrite)
- `lib/jevrag/store.ts` — zustand store: messages, SSE event application, uploads, status
- `lib/jevrag/types.ts` — shared types mirroring the backend SSE protocol
- `lib/jevrag/bench-api.ts` — bench client + types (scenarios, runs, results, summary shapes)
- `lib/jevrag/bench-store.ts` — bench state: selection, run lifecycle, 3s polling while running
- `components/jevrag/chat-panel.tsx` — message list, compare rows, composer, empty state
- `components/jevrag/chat-message.tsx` — markdown + citation chips + meta + verification badge
- `components/jevrag/trace-panel.tsx` — Jev decisions with probability bars, retrieval, timings
- `components/jevrag/sidebar.tsx` — conversations + documents + upload dropzone
- `components/jevrag/status-pill.tsx` — cloud/jev/docs health indicator
- `components/jevrag/ui-bits.tsx` — shared atoms (ModeBadge, ProbabilityBar, CitationChip…)
- `components/jevrag/bench/bench-view.tsx` — benchmark lab layout: header, scenario grid, run controls, progress
- `components/jevrag/bench/results-dashboard.tsx` — metric cards, per-scenario charts (recharts),
  pairwise/gate/abstention panels; `liveSummary` client-side aggregation while a run is in flight
- `components/jevrag/bench/results-table.tsx` — per-question table with filters and drill-down
  (answer, reference, judge reason, retrieved files, timings, sufficiency/verification)

## Local Contracts

- Never call the backend with absolute URLs or `XTransformPort` — only relative `/backend-api/*`
  (the Next.js rewrite in `next.config.ts` proxies to FastAPI :8000 in every context)
- The SSE event schema is owned jointly with `backend/AGENTS.md`; update both sides together.
  v2: the `routing` event carries effort routing (`{effort, model, probabilities, confidence}`)
  and `done` may add `quality_score`, `best_of`, `retried` — see `lib/jevrag/types.ts`
- Keep the backend mount symmetrical: FastAPI serves both `/api/*` and `/backend-api/*`
- One user-visible route only: `/` (sandbox constraint)
- No blue/indigo palette: hybrid = emerald, traditional = sky/amber accents, neutrals = zinc
  (bench charts: traditional #0ea5e9, hybrid #10b981)
- All state flows through the zustand store; components stay presentational where possible
- Benchmarks polling only while a run is active (3s interval; stopped on completion/failure)
- `lib/jevrag/types.ts` was lost from git once (recreated 2026-09-28): it is a build
  blocker when missing — always commit it with any protocol change

## Work Guidance

- Streaming UX: apply SSE events via `applyEvent`; stage text shows pipeline progress
  ("retrieving…", "jev reranking…", "answering…")
- Compare mode runs two concurrent streams grouped by `pairKey`, rendered side-by-side
- Self-healing: `init()` awaits `ensureBackend()`; failed streams retry once after re-ensuring
- Markdown rendering uses react-markdown with citation chips injected by splitting `[n]`
  patterns in string children (see `withCitations`)

## Verification

- `bun run lint` (must be clean; vendor/ and models/ are ignored in eslint config)
- Live browser check (mandatory): chat in both modes, compare, upload, trace panel, mobile
  viewport has no horizontal overflow

## Child DOX Index

| Child | Scope |
| --- | --- |
| (none) | Flat component structure; add child docs only if a subfolder becomes a durable boundary |
