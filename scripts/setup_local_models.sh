#!/usr/bin/env bash
# setup_local_models.sh — Jev-RAG local model setup (background-safe, logs everything)
# 1) Downloads Jev-Style-0.8B-Decision-v3-GGUF repo files (scripts + Q4_K_M model)
# 2) Clones llama.cpp (shallow)
# 3) Builds the `jev-score` scorer binary via the repo's build_jev_score.sh
set -uo pipefail

ROOT="/home/z/my-project"
MODELS_DIR="$ROOT/models/jev-style"
LLAMA_DIR="$ROOT/vendor/llama.cpp"
HF_REPO="chaoliangUNSW/Jev-Style-0.8B-Decision-v3-GGUF"
GGUF="Jev-Style-0.8B-Decision-v3-Q4_K_M.gguf"
EXPECTED_GGUF_BYTES=529296864

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [setup-local] $*"; }

mkdir -p "$MODELS_DIR" "$ROOT/vendor" "$ROOT/logs"
cd "$MODELS_DIR"

log "=== Phase 1: toolchain check ==="
MISSING=""
for t in git curl python3; do command -v "$t" >/dev/null 2>&1 || MISSING="$MISSING $t"; done
if [ -n "$MISSING" ]; then log "FATAL: missing required tools:$MISSING"; exit 1; fi
log "cmake: $(command -v cmake || echo MISSING)"
log "g++:   $(command -v g++ || echo MISSING)"
log "make:  $(command -v make || echo MISSING)"
if ! command -v g++ >/dev/null 2>&1; then
  log "FATAL: no C++ compiler (g++) available — cannot build llama.cpp/jev-score"
  exit 5
fi
# Bootstrap cmake via pip if absent (lands in /home/z/.venv/bin)
if ! command -v cmake >/dev/null 2>&1; then
  log "cmake missing — installing via pip"
  pip3 install -q cmake ninja && export PATH="/home/z/.venv/bin:$PATH" || log "WARN: pip cmake install failed"
  log "cmake after pip: $(command -v cmake || echo STILL-MISSING)"
fi

log "=== Phase 2: download Jev-Style repo files (scripts, configs) ==="
TREE=$(curl -sL -m 60 "https://huggingface.co/api/models/$HF_REPO/tree/main?recursive=true")
FILES=$(echo "$TREE" | python3 -c "import json,sys; print('\n'.join(f['path'] for f in json.load(sys.stdin) if f.get('type') != 'directory' and not f['path'].endswith(('.gguf','.png','.jpg','.jpeg','.webp','.svg','.data.json'))))" 2>/dev/null || true)
log "small files to fetch: $(echo "$FILES" | tr '\n' ' ')"
for f in $FILES; do
  mkdir -p "$(dirname "$MODELS_DIR/$f")"
  if curl -sL --fail -m 120 --retry 3 -o "$MODELS_DIR/$f" "https://huggingface.co/$HF_REPO/resolve/main/$f"; then
    log "fetched: $f"
  else
    log "WARN: failed to fetch $f"
  fi
done

log "=== Phase 3: download $GGUF (expected $EXPECTED_GGUF_BYTES bytes) ==="
CURRENT_SIZE=$(stat -c%s "$MODELS_DIR/$GGUF" 2>/dev/null || echo 0)
if [ "$CURRENT_SIZE" = "$EXPECTED_GGUF_BYTES" ]; then
  log "GGUF already present with correct size; skipping"
else
  if curl -sL --fail --retry 3 -C - -o "$MODELS_DIR/$GGUF" "https://huggingface.co/$HF_REPO/resolve/main/$GGUF"; then
    log "GGUF download complete: $(stat -c%s "$MODELS_DIR/$GGUF") bytes"
  else
    log "FATAL: GGUF download failed (partial: $(stat -c%s "$MODELS_DIR/$GGUF" 2>/dev/null || echo 0) bytes)"
    exit 2
  fi
fi

log "=== Phase 3b: patch runtime for reduced llama.cpp context (sandbox memory) ==="
# The stock runtime hardcodes a 32k llama.cpp context (~900MB KV cache on CPU) which
# the 4GB sandbox OOM-kills. Our patch makes the context env-tunable via
# JEV_SCORE_N_CTX (the backend sets 8192 via JEVRAG_JEV_SCORE_N_CTX); input limits
# scale down so over-budget requests still get the clean 422 budget rejection.
python3 - <<'PYEOF'
import re
from pathlib import Path

rt = Path("models/jev-style/jev_style_decision_gguf.py")
src = rt.read_text()
if "Jev-RAG patch" in src:
    print("runtime already patched; skipping")
else:
    old = 'CONTEXT_LIMIT = 25_600          # state + question + options + readout\nHARD_HEAD_MAX = 2048            # question + options + readout\nQTYPES = ("choice", "score", "noul")\nHERE = Path(__file__).resolve().parent\n'
    patch = old + '''
# --- Jev-RAG patch: env-tunable llama.cpp context (JEV_SCORE_N_CTX) -----------------
# The stock 32k context allocates ~900MB of KV cache on CPU. Jev-RAG workloads use
# <=3k tokens, so JEV_SCORE_N_CTX (e.g. 8192) cuts ~700MB RSS and prevents OOM kills
# in memory-constrained sandboxes. Setting it opts out of the model's full 25.6k-token
# input mode: input limits scale down so over-budget requests still get the clean
# budget rejection (422) instead of a llama.cpp context overflow.
import os as _os
_ctx_env = _os.environ.get("JEV_SCORE_N_CTX", "").strip()
if _ctx_env.isdigit() and int(_ctx_env) < CONTEXT_LIMIT + 3 * HARD_HEAD_MAX:
    LLAMA_N_CTX = int(_ctx_env)
    CONTEXT_LIMIT = max(1024, LLAMA_N_CTX // 2)
    HARD_HEAD_MAX = max(256, LLAMA_N_CTX // 8)
else:
    LLAMA_N_CTX = 32768
assert LLAMA_N_CTX >= CONTEXT_LIMIT + 3 * HARD_HEAD_MAX
# --- end Jev-RAG patch --------------------------------------------------------------
'''
    if old not in src:
        raise SystemExit("FATAL: runtime constant block not found — upstream changed; port the patch manually")
    src = src.replace(old, patch, 1)
    old2 = 'GGUF_FILES = {q: f"{MODEL_NAME}-{q}.gguf" for q in ("F16", "Q8_0", "Q4_K_M")}\nLLAMA_N_CTX = 32768        # >= 25,600-token context + room for question suffixes\nassert LLAMA_N_CTX >= CONTEXT_LIMIT + 3 * HARD_HEAD_MAX\nMANY_MODES = ("exact", "batched")\n'
    new2 = 'GGUF_FILES = {q: f"{MODEL_NAME}-{q}.gguf" for q in ("F16", "Q8_0", "Q4_K_M")}\nMANY_MODES = ("exact", "batched")\n'
    if old2 not in src:
        raise SystemExit("FATAL: LLAMA_N_CTX block not found — upstream changed; port the patch manually")
    src = src.replace(old2, new2, 1)
    rt.write_text(src)
    print("patched jev_style_decision_gguf.py (JEV_SCORE_N_CTX support)")
PYEOF

log "=== Phase 4: clone llama.cpp (shallow, master) ==="
if [ ! -d "$LLAMA_DIR/.git" ]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR" || { log "FATAL: llama.cpp clone failed"; exit 3; }
else
  log "llama.cpp already cloned"
fi
log "llama.cpp HEAD: $(git -C "$LLAMA_DIR" rev-parse --short HEAD)"

log "=== Phase 5: build jev-score ==="
if [ ! -f build_jev_score.sh ]; then
  log "FATAL: build_jev_score.sh not found in $MODELS_DIR"
  exit 4
fi
log "--- build_jev_score.sh contents (for review) ---"
cat build_jev_score.sh
log "--- end script contents ---"
log "running: sh ./build_jev_score.sh \"$LLAMA_DIR\" (this compiles llama.cpp; may take several minutes)"
sh ./build_jev_score.sh "$LLAMA_DIR"
RC=$?
log "build_jev_score.sh exit code: $RC"
log "=== jev-score binaries found ==="
python3 - <<'PY'
import pathlib
found = False
for base in ("/home/z/my-project/models/jev-style", "/home/z/my-project/vendor/llama.cpp"):
    for p in sorted(pathlib.Path(base).rglob("jev-score*")):
        print(p, p.stat().st_size)
        found = True
if not found:
    print("(none found)")
PY
if [ "$RC" -eq 0 ]; then
  log "STATUS: SUCCESS"
else
  log "STATUS: BUILD_FAILED rc=$RC — inspect this log and build_jev_score.sh"
fi
