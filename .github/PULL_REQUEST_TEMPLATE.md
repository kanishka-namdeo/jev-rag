<!--
Thanks for the PR! A few things that make review fast here.
All of these are also in CONTRIBUTING.md — the short version:
measured claims, both directions, no secrets in diffs, docs updated.
-->

## What

<!-- One-sentence summary of the change. -->

## Why

<!-- The failure mode / measured gap this addresses. -->

## Evidence

- [ ] Tests green: `cd backend && .venv/bin/python -m pytest tests -v`
- [ ] Lint green: `bun run lint`
- [ ] If pipelines/config changed: benchmark scenario(s) run, numbers reported **in both directions** (hybrid can lose)
- [ ] If behavior changed: docs updated ([docs/setup.md](../docs/setup.md) / [docs/hybrid-design.md](../docs/hybrid-design.md) / `backend/.env.example`)

## Safety

- [ ] No secrets, keys, `.env` contents, `models/`, `db/`, or `.next/` files in this diff
- [ ] No new cloud dependencies beyond the OpenAI-compatible endpoint (local-first contract)
- [ ] DOX pass done: nearest AGENTS.md still accurate for the files I touched
