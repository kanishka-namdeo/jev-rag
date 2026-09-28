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

log "starting backend (uvicorn :8000)"
( cd "$ROOT/backend" && exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 ) &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

log "starting frontend (next dev :3000)"
cd "$ROOT"
bun run dev
