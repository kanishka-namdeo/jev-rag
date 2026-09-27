#!/usr/bin/env bash
# setup_backend.sh — create backend/.venv and install Python dependencies via uv
set -euo pipefail
ROOT="/home/z/my-project"
BACKEND="$ROOT/backend"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [setup-backend] $*"; }

command -v uv >/dev/null 2>&1 || { log "FATAL: uv not found"; exit 1; }
cd "$BACKEND"

log "creating venv (python 3.12) at backend/.venv"
uv venv --python 3.12 .venv

log "installing requirements.txt via uv pip (may take a few minutes)"
uv pip install --python .venv/bin/python -r requirements.txt

log "sanity-checking imports"
.venv/bin/python - <<'PY'
import fastapi, chromadb, openai, sqlalchemy
print("core imports ok:", "fastapi", fastapi.__version__, "| chromadb", chromadb.__version__)
import fastembed
print("fastembed ok:", fastembed.__version__)
try:
    import jev_style
    print("jev_style ok:", getattr(jev_style, "__version__", "unknown-version"))
except Exception as e:
    print("jev_style IMPORT FAILED:", type(e).__name__, e)
PY
log "STATUS: SUCCESS — backend/.venv ready"
