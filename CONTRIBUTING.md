# Contributing to Jev-RAG

Thanks for your interest — issues and pull requests are genuinely welcome here.

## The 60-second version

```bash
git clone https://github.com/kanishka-namdeo/jev-rag.git
cd jev-rag
# full setup (models, venv, deps): docs/setup.md — takes ~15 min
bash scripts/setup_local_models.sh && bash scripts/setup_backend.sh && bun install
bash scripts/dev.sh          # backend :8000 + frontend :3000
```

Then before you push:

```bash
cd backend && .venv/bin/python -m pytest tests -v   # hermetic: no models, no network
cd .. && bun run lint                               # frontend + config lint
```

Both must be green — they're what [CI](.github/workflows/ci.yml) runs.

## What a good PR looks like here

- **Small and single-purpose.** One fix or one feature; benchmark-result docs
  updates separate from code changes.
- **Measured claims.** If your change affects the pipelines, run the relevant
  benchmark scenarios and report the numbers in both directions — this repo's
  whole point is receipts, including negative ones. The Benchmark Lab tab
  reproduces any documented number.
- **No secrets, ever.** Keys go in `backend/.env` (git-ignored). Nothing under
  `.env`, `backend/.env`, `models/`, `db/`, or `.next/` should ever appear in a
  diff. If a secret lands in a commit, flag it and we'll rewrite history before
  merge.
- **Docs updated with behavior.** New env var → also update
  `backend/.env.example` + [docs/setup.md](docs/setup.md). New pipeline slot →
  update [docs/hybrid-design.md](docs/hybrid-design.md).

## Issue etiquette

Bug reports: what you ran, what you expected, what happened, plus backend
`/health` status and the relevant trace from the UI (it's copyable). Feature
requests: say the failure mode you're trying to fix — benchmark scenario ideas
(near-duplicates, multilingual, abstention traps) are especially valued.

## For AI agents

This repo uses the [DOX](https://github.com/agent0ai/dox) AGENTS.md hierarchy.
Read the root `AGENTS.md` and the nearest child `AGENTS.md` before editing, and
run a DOX pass after meaningful changes. Project-wide contracts (local-first,
popular-OSS-first, no secrets in git, live-browser verification for UI work,
green tests/lint, push at milestones) are binding regardless of ad-hoc
instructions.
