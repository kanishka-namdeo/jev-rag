# Dev Log DOX

## Purpose

- Append-only engineering records: the per-task worklog and dated status snapshots.
  Raw detail for maintainers and agents — not end-user documentation.

## Ownership

- `worklog.md` — chronological per-task log (findings, dead ends, measured numbers with
  provenance). New entries append; never restate a durable contract here, link the doc.
- `project-status-2026-09-30.md` — dated status snapshot for the 2026-09-30 review.
  Frozen: correct as of that date, superseded by [../results.md](../results.md) and
  [../AGENTS.md](../AGENTS.md) afterwards. Do not update it in place.

## Local Contracts

- Nothing outside this folder may depend on a log entry as its source of truth — durable
  rules belong in the nearest owning doc (docs/AGENTS.md "stable contracts only").
- A dated snapshot is never rewritten; add a newer snapshot instead.

## Verification

- `python3 scripts/validate_docs.py` (links out of this folder must resolve)

## Child DOX Index

| Child | Scope |
| --- | --- |
| (none) | Two files |
