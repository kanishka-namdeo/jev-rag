#!/usr/bin/env bash
# backend_service.sh — runs the FastAPI backend (uvicorn) for the Jev-RAG app.
# Started by .zscripts/dev.sh via mini-services/backend (or manually: bash scripts/backend_service.sh).
# Portable: resolves the repo root from this script's location (docs/setup.md).
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)/backend"
export PYTHONUNBUFFERED=1
# Reduce glibc allocator fragmentation for the long-lived bench process
export MALLOC_ARENA_MAX=2

if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
  echo "backend venv missing — run scripts/setup_backend.sh first" >&2
  sleep 5
  exit 1
fi

cd "$BACKEND_DIR"
exec "$BACKEND_DIR/.venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
