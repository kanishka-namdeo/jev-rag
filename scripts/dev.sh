#!/usr/bin/env bash
# dev.sh — run the full Jev-RAG stack locally (backend + frontend).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
log() { echo "$(date '+%H:%M:%S') [dev] $*"; }

if [ ! -x "$ROOT/backend/.venv/bin/python" ]; then
  log "backend venv missing — running scripts/setup_backend.sh"
  bash "$ROOT/scripts/setup_backend.sh"
fi
if [ ! -f "$ROOT/backend/.env" ]; then
  log "backend/.env missing — copying from backend/.env.example (fill in your API key!)"
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
fi
if [ ! -f "$ROOT/models/jev-style/build/jev-score" ]; then
  log "local Jev-style model/scorer missing — running scripts/setup_local_models.sh"
  bash "$ROOT/scripts/setup_local_models.sh"
fi

log "starting backend (uvicorn via app.main — host/port from backend/.env)"
( cd "$ROOT/backend" && exec .venv/bin/python -m app.main ) &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

log "starting frontend (next dev :3000)"
cd "$ROOT"
# Local-first contract: no telemetry. Next.js pings home by default in dev;
# NEXT_TELEMETRY_DISABLED=1 also prefixes the dev/build/start scripts in
# package.json, so bare `bun run dev` is covered too.
export NEXT_TELEMETRY_DISABLED=1
bun run dev
