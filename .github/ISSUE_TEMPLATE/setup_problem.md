---
name: 🧰 Setup or run problem
about: Installation, launch, upload or hybrid-mode failures
title: "[setup] "
labels: ["setup"]
---

Before filing, check https://github.com/kanishka-namdeo/jev-rag/blob/main/docs/troubleshooting.md — common failures carry copy-paste fixes there.

**What you ran** (exact command)

**What you expected / what happened**

**OS and how you ran it** (native Linux / macOS / WSL2 Ubuntu-24.04)

**`GET /api/system/status` output** — open the status pill and press "Copy status JSON".
`/api/system/health` is not useful here: it answers `ok` without checking anything.

**Backend log tail** (`logs/backend.log`, or the uvicorn stdout in your terminal)

**Mode and scenario** (traditional / hybrid / compare; a benchmark run id if relevant)
