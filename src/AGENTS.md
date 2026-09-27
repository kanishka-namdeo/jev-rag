# Frontend DOX (src/)

## Purpose

- Own the Next.js 16 App Router UI: chat with SSE streaming, mode selection (traditional /
  hybrid / compare), document management sidebar, Jev decision trace panel, system status.

## Ownership

- `app/page.tsx` — page shell: header, sidebar, chat, trace panel, responsive layout
- `app/layout.tsx` — fonts, metadata, theme provider, toasters
- `app/api/ensure-backend/route.ts` — self-healing backend launcher (spawns uvicorn detached)
- `lib/jevrag/api.ts` — backend client; ALL backend calls go through `/backend-api/*` (Next rewrite)
- `lib/jevrag/store.ts` — zustand store: messages, SSE event application, uploads, status
- `lib/jevrag/types.ts` — shared types mirroring the backend SSE protocol
- `components/jevrag/chat-panel.tsx` — message list, compare rows, composer, empty state
- `components/jevrag/chat-message.tsx` — markdown + citation chips + meta + verification badge
- `components/jevrag/trace-panel.tsx` — Jev decisions with probability bars, retrieval, timings
- `components/jevrag/sidebar.tsx` — conversations + documents + upload dropzone
- `components/jevrag/status-pill.tsx` — cloud/jev/docs health indicator
- `components/jevrag/ui-bits.tsx` — shared atoms (ModeBadge, ProbabilityBar, CitationChip…)

## Local Contracts

- Never call the backend with absolute URLs or `XTransformPort` — only relative `/backend-api/*`
  (the Next.js rewrite in `next.config.ts` proxies to FastAPI :8000 in every context)
- The SSE event schema is owned jointly with `backend/AGENTS.md`; update both sides together
- Keep the backend mount symmetrical: FastAPI serves both `/api/*` and `/backend-api/*`
- One user-visible route only: `/` (sandbox constraint)
- No blue/indigo palette: hybrid = emerald, traditional = amber, neutrals = zinc
- All state flows through the zustand store; components stay presentational where possible

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
