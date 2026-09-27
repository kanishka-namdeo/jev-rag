# Docs DOX

## Purpose

- Durable design documentation: architecture, hybrid pipeline design (with research grounding),
  and the SSE API protocol shared by backend and frontend.

## Ownership

- `architecture.md` — system components and data flow
- `hybrid-design.md` — the Jev / System-One design rationale, research sources, latency notes
- `api.md` — REST + SSE protocol reference

## Local Contracts

- Docs describe stable contracts only; changelogs and diary entries do not belong here
- Every external claim (model facts, prices, links) must carry its source URL

## Verification

- Manual review on change; cross-check protocol tables against `backend/app/rag/pipelines.py`
  and `src/lib/jevrag/types.ts` after any protocol change

## Child DOX Index

| Child | Scope |
| --- | --- |
| (none) | Flat docs directory |
