#!/usr/bin/env bash
# setup_local_models.sh — Jev-RAG local model setup (background-safe, logs everything)
# 1) Downloads Jev-Style-0.8B-Decision-v3-GGUF repo files (scripts + Q4_K_M model)
# 2) Clones llama.cpp (shallow)
# 3) Builds the `jev-score` scorer binary via the repo's build_jev_score.sh
#
# Portable across machines (see docs/setup.md): the repo root is derived from this
# script's location, file sizes are checked with python3 (not GNU-only `stat -c%s`),
# and the cmake bootstrap honors JEVRAG_PIP_INDEX_URL for mirror-restricted networks.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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
# Bootstrap cmake via pip if absent (portable: user-site first, venv-python fallback).
# JEVRAG_PIP_INDEX_URL overrides the index (e.g. a mirror when pypi.org is
# unreachable — see docs/setup.md → troubleshooting).
if ! command -v cmake >/dev/null 2>&1; then
  log "cmake missing — attempting pip bootstrap"
  PIP_INDEX_ARGS=""
  [ -n "${JEVRAG_PIP_INDEX_URL:-}" ] && PIP_INDEX_ARGS="-i $JEVRAG_PIP_INDEX_URL"
  # --user works for system Pythons (lands in the user-base bin); the plain
  # fallback covers venv Pythons (installs into the active venv, already on PATH).
  python3 -m pip install --user -q $PIP_INDEX_ARGS cmake ninja \
    || python3 -m pip install -q $PIP_INDEX_ARGS cmake ninja \
    || log "WARN: pip cmake bootstrap failed"
  USER_BASE="$(python3 -m site --user-base 2>/dev/null || true)"
  [ -n "$USER_BASE" ] && export PATH="$USER_BASE/bin:$PATH"
  log "cmake after bootstrap: $(command -v cmake || echo STILL-MISSING — install via your OS package manager, e.g. 'apt install cmake' or 'brew install cmake', then re-run)"
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

# size helper: python3-based (portable — `stat -c%s` is GNU-only and fails on macOS)
filesize() { python3 -c 'import os,sys; p=sys.argv[1]; print(os.path.getsize(p) if os.path.exists(p) else 0)' "$1" 2>/dev/null || echo 0; }

log "=== Phase 3: download $GGUF (expected $EXPECTED_GGUF_BYTES bytes) ==="
CURRENT_SIZE=$(filesize "$MODELS_DIR/$GGUF")
if [ "$CURRENT_SIZE" = "$EXPECTED_GGUF_BYTES" ]; then
  log "GGUF already present with correct size; skipping"
else
  if curl -sL --fail --retry 3 -C - -o "$MODELS_DIR/$GGUF" "https://huggingface.co/$HF_REPO/resolve/main/$GGUF"; then
    log "GGUF download complete: $(filesize "$MODELS_DIR/$GGUF") bytes"
  else
    log "FATAL: GGUF download failed (partial: $(filesize "$MODELS_DIR/$GGUF") bytes)"
    exit 2
  fi
fi

log "=== Phase 3b: patch runtime for reduced llama.cpp context (sandbox memory) ==="
# Jev-RAG fix: run the patch blocks against an absolute path — this script cd's into
# $MODELS_DIR for the download/build phases, which broke the original root-relative
# Path("models/jev-style/...") lookups on fresh setups (patches silently never applied).
export JEV_PATCH_TARGET="$MODELS_DIR/jev_style_decision_gguf.py"
python3 - <<'PYEOF'
import re
from pathlib import Path
import os

rt = Path(os.environ["JEV_PATCH_TARGET"])
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

log "=== Phase 3c: patch runtime for trimmed sequence/output buffers (sandbox memory) ==="
# Stock flags (--n-seq-max 17 --n-outputs-max 256) size for many_mode="batched"
# fan-out; Jev-RAG's many_mode="exact" requests always run in jev-score sequential
# mode using only sequences 0/1, so 2/32 cuts ~306MB RSS with bit-identical decoding
# (verified by scripts/verify_jev_runtime_parity.py). The backend exports
# JEV_SCORE_N_SEQ_MAX / JEV_SCORE_N_OUTPUTS_MAX via JEVRAG_JEV_SCORE_* settings.
python3 - <<'PYEOF'
from pathlib import Path
import os

rt = Path(os.environ["JEV_PATCH_TARGET"])
src = rt.read_text()
if "JEV_SCORE_N_SEQ_MAX" in src:
    print("runtime already has allocation-trim patch; skipping")
else:
    anchor = "assert LLAMA_N_CTX >= CONTEXT_LIMIT + 3 * HARD_HEAD_MAX\n"
    env_block = anchor + '''
# --- Jev-RAG patch: per-sequence state + outputs-buffer overrides (spawn-time) --------
# llama.cpp reserves per-sequence recurrent state (~23.6 MB/seq on this hybrid
# recurrent+attention model) and an outputs row buffer (n_vocab * 4 B per row). The
# stock flags (n-seq-max 17 / n-outputs-max 256) size for many_mode="batched" fan-out;
# Jev-RAG uses the default many_mode="exact", whose requests run in jev-score
# "sequential" mode where only sequences 0 (shared prefix) and 1 (question) are ever
# used and each question carries <= 4 option slots. Measured on this sandbox:
# 17/256 -> 1,538 MB RSS vs 2/32 -> 1,232 MB RSS (306 MB saved) with identical
# sequential-mode decoding. Env overrides are read at SPAWN time so respawns pick
# them up; unset values keep upstream defaults.
_JEV_N_SEQ_MAX = _os.environ.get("JEV_SCORE_N_SEQ_MAX", "").strip()
_JEV_N_OUTPUTS_MAX = _os.environ.get("JEV_SCORE_N_OUTPUTS_MAX", "").strip()
# --- end Jev-RAG patch --------------------------------------------------------------
'''
    if anchor not in src:
        raise SystemExit("FATAL: context assert anchor not found — upstream changed; port the patch manually")
    src = src.replace(anchor, env_block, 1)
    old_cmd = '''        cmd = [str(self.binary), "--model", str(self.gguf), "--n-ctx", str(LLAMA_N_CTX), "--n-ubatch", str(n_ubatch),
               "--ngl", str(n_gpu_layers), "--flash-attn", flash_attn, "--n-seq-max", "17", "--n-outputs-max", "256"]
        if threads:
            cmd += ["--threads", str(threads)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=stderr if stderr is not None else subprocess.DEVNULL, text=True, bufsize=1)'''
    new_cmd = '''        n_seq_max = int(_JEV_N_SEQ_MAX) if _JEV_N_SEQ_MAX.isdigit() else 17
        n_outputs_max = int(_JEV_N_OUTPUTS_MAX) if _JEV_N_OUTPUTS_MAX.isdigit() else 256
        n_outputs_max = max(n_outputs_max, 2, n_seq_max)  # libllama asserts n_out >= max(2, n_seq)
        cmd = [str(self.binary), "--model", str(self.gguf), "--n-ctx", str(LLAMA_N_CTX), "--n-ubatch", str(n_ubatch),
               "--ngl", str(n_gpu_layers), "--flash-attn", flash_attn, "--n-seq-max", str(n_seq_max),
               "--n-outputs-max", str(n_outputs_max)]
        if threads:
            cmd += ["--threads", str(threads)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=stderr if stderr is not None else subprocess.DEVNULL, text=True, bufsize=1)'''
    if old_cmd not in src:
        raise SystemExit("FATAL: spawn cmd block not found — upstream changed; port the patch manually")
    src = src.replace(old_cmd, new_cmd, 1)
    rt.write_text(src)
    print("patched jev_style_decision_gguf.py (JEV_SCORE_N_SEQ_MAX / JEV_SCORE_N_OUTPUTS_MAX support)")
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
MODELS_DIR="$MODELS_DIR" LLAMA_DIR="$LLAMA_DIR" python3 - <<'PY'
import os, pathlib
found = False
for base in (os.environ["MODELS_DIR"], os.environ["LLAMA_DIR"]):
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
