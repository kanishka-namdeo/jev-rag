# Windows Setup Guide (WSL2)

This document captures the complete setup process for running Jev-RAG on Windows 10/11 using WSL2.

**System:** Windows 10/11 with WSL2  
**Date:** 2026-09-30  
**Project Location:** `d:\test_jev\jev-rag` (Windows) → `/mnt/d/test_jev/jev-rag` (WSL2)

---

## Prerequisites

### Windows Requirements
- Windows 10 version 2004+ or Windows 11
- Administrator access
- Virtualization enabled in BIOS/UEFI

### Installation Steps

#### Step 1: Install WSL2

Open PowerShell as Administrator and run:

```powershell
wsl --install -d Ubuntu-24.04
```

**Important:** This requires a system restart. After restart, Ubuntu will complete installation automatically.

**Verification:**
```powershell
wsl -l -v
```

Expected output:
```
  NAME            STATE           VERSION
* Ubuntu-24.04    Running         2
```

**Troubleshooting:**
- If you see "Catastrophic failure" or `E_UNEXPECTED`, restart your system
- If WSL commands hang, run `wsl --shutdown` and retry
- If Ubuntu installation fails, try `wsl --unregister Ubuntu-24.04` then reinstall

#### Step 2: Configure Ubuntu User

First time you launch Ubuntu, it will prompt for username and password:

```powershell
wsl -d Ubuntu-24.04
```

Create a user (e.g., `jevrag` with password `jevrag`). This user will have sudo access.

#### Step 3: Install System Dependencies

From PowerShell, run commands inside WSL2:

```powershell
wsl -d Ubuntu-24.04 -- bash -c "
sudo apt update && sudo apt install -y python3.12 python3.12-venv python3.12-dev build-essential cmake curl git
"
```

**Verification:**
```powershell
wsl -d Ubuntu-24.04 -- bash -c "python3.12 --version && g++ --version | head -1 && cmake --version | head -1"
```

Expected: Python 3.12.x, g++ version, cmake version 3.14+

#### Step 4: Install uv (Python Package Manager)

```powershell
wsl -d Ubuntu-24.04 -- bash -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
```

**Note:** uv installs to `~/.local/bin/uv`. You may need to add it to PATH or use the full path.

**Verification:**
```powershell
wsl -d Ubuntu-24.04 -- bash -c "export PATH=\$HOME/.local/bin:\$PATH && uv --version"
```

#### Step 5: Install bun (JavaScript Runtime)

```powershell
wsl -d Ubuntu-24.04 -- bash -c "curl -fsSL https://bun.sh/install | bash"
```

**Note:** bun installs to `~/.bun/bin/bun`.

**Verification:**
```powershell
wsl -d Ubuntu-24.04 -- bash -c "export PATH=\$HOME/.bun/bin:\$PATH && bun --version"
```

---

## Project Setup

All subsequent commands run inside WSL2. For brevity, we'll show the bash commands. Prefix each with:

```powershell
wsl -d Ubuntu-24.04 -- bash -c "..."
```

Or open a WSL2 shell:

```powershell
wsl -d Ubuntu-24.04
cd /mnt/d/test_jev/jev-rag
```

### Step 6: Download Jev-Style Model and Build jev-score

```bash
cd /mnt/d/test_jev/jev-rag
bash scripts/setup_local_models.sh
```

**What this does:**
1. Downloads Jev-Style GGUF model (0.53 GB, 529,296,864 bytes) from HuggingFace
2. Clones llama.cpp repository
3. Builds `jev-score` binary (takes 5-15 minutes)
4. Applies memory optimization patches

**Expected output:** `STATUS: SUCCESS` at the end

**Verification:**
```bash
ls -la models/jev-style/build/jev-score
# Should show executable ~255KB
```

**Troubleshooting:**
- If build fails, ensure you have 2+ GB free RAM
- Script is idempotent — safe to re-run
- Check `logs/setup-local-models.log` for details

### Step 7: Set Up Backend Python Environment

```bash
cd /mnt/d/test_jev/jev-rag
bash scripts/setup_backend.sh
```

**What this does:**
1. Creates `backend/.venv` with Python 3.12
2. Installs all dependencies from `backend/requirements.txt`
3. Verifies critical imports

**Expected output:** `STATUS: SUCCESS`

**Verification:**
```bash
cd backend
.venv/bin/python -c "import fastapi, chromadb, fastembed; print('OK')"
```

### Step 8: Configure Backend Environment

```bash
cd /mnt/d/test_jev/jev-rag
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set:

```bash
JEVRAG_DASHSCOPE_API_KEY=your-actual-api-key-here
```

**Important:** The API key is required for cloud LLM calls. Get it from your Dashscope account.

### Step 9: Install Frontend Dependencies

```bash
cd /mnt/d/test_jev/jev-rag
export PATH="$HOME/.bun/bin:$PATH"
bun install
```

**Expected:** Creates `node_modules/` directory

**Verification:**
```bash
bun run lint
# Should complete without errors
```

---

## Verification Checklist

Run these tests to confirm everything is working:

### 1. Backend Health Check

```bash
cd /mnt/d/test_jev/jev-rag/backend
.venv/bin/python -c "
from app.config import get_settings
from app.rag.retriever import Embedder
from app.rag.crossenc import CrossEncoderReranker
from app.llm.jev_engine import JevEngine
print('✓ All imports successful')
"
```

### 2. Backend Test Suite

```bash
cd /mnt/d/test_jev/jev-rag/backend
.venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

### 3. LLM Endpoint Test

```bash
cd /mnt/d/test_jev/jev-rag/backend
.venv/bin/python -c "
from app.config import get_settings
from app.llm.dashscope import DashscopeLLM
s = get_settings()
llm = DashscopeLLM(s)
reply = llm.complete(model=s.llm_model_default, system='prober', user='say ok', max_tokens=8)
print('✓ LLM reply:', reply[0])
"
```

Expected: Returns a short response from the LLM

### 4. Frontend Lint

```bash
cd /mnt/d/test_jev/jev-rag
export PATH="$HOME/.bun/bin:$PATH"
bun run lint
```

Expected: No errors

---

## Running the Project

### Start Development Servers

```bash
cd /mnt/d/test_jev/jev-rag
bash scripts/dev.sh
```

This starts:
- Backend API server on `http://localhost:8000`
- Frontend UI on `http://localhost:3000`

**First startup notes:**
- Backend loads the GGUF model (~15 seconds once caches are warm; a first boot adds the one-time embedding-model download)
- Embedding model downloads on first use (~225 MB, one-time)
- Hybrid pipeline queries take ~30 seconds on 2 cores

### Access the UI

Open your browser: `http://localhost:3000`

1. Upload a document via the sidebar
2. Ask a question in any mode:
   - **Traditional** — standard RAG
   - **Hybrid · Jev** — uses the local decision model
   - **Compare** — side-by-side comparison

### Stop the Servers

Press `Ctrl+C` in the terminal running `dev.sh`

---

## Running Benchmarks

### Via UI (Recommended)

1. Open `http://localhost:3000`
2. Navigate to **Benchmarks** tab
3. Select scenarios and run

### Via Command Line

```bash
cd /mnt/d/test_jev/jev-rag/backend
.venv/bin/python scripts/run_testbench.py \
  --arms base,gate-none,always-hard,oracle-gate \
  --scenarios squad,hotpotqa,triviaqa,wiki2,musique \
  --label "H-GATE full power" \
  --window-minutes 100000
```

**Note:** Full benchmark runs take 2-4 hours and cost ~$0.30-0.60 in API calls.

---

## Current System State (2026-09-30) — FULLY SET UP

**All completed:**
- ✅ WSL2 Ubuntu-24.04 installed and running
- ✅ Python 3.12.3 installed
- ✅ uv v0.12.21 installed at `/root/.local/bin/uv`
- ✅ bun v1.4.2 installed at `/root/.bun/bin/bun`
- ✅ System dependencies (build-essential, cmake, git, curl, unzip) installed
- ✅ Jev-Style GGUF model downloaded (0.53 GB, 529,296,864 bytes)
- ✅ jev-score binary built (250K at `models/jev-style/build/jev-score`)
- ✅ Backend venv created with 132 packages (FastAPI 0.142.0)
- ✅ Frontend dependencies installed (827 packages)
- ✅ Backend `.env` configured with Dashscope API key
- ✅ All 121 backend tests passed
- ✅ Frontend lint passed
- ✅ LLM endpoint verified (qwen3.7-plus responding)

---

## Troubleshooting

### WSL2 Issues

**Problem:** "Catastrophic failure" or `E_UNEXPECTED`  
**Solution:** Restart Windows system

**Problem:** WSL commands hang  
**Solution:** Run `wsl --shutdown` in PowerShell, then retry

**Problem:** Ubuntu installation fails  
**Solution:** 
```powershell
wsl --unregister Ubuntu-24.04
wsl --install -d Ubuntu-24.04
```

### Build Issues

**Problem:** jev-score build fails  
**Solution:** Ensure you have 2+ GB free RAM. Check `logs/setup-local-models.log`

**Problem:** Python imports fail  
**Solution:** Re-run `bash scripts/setup_backend.sh`

### Network Issues

**Problem:** Can't download models  
**Solution:** Check internet connectivity. HuggingFace and GitHub must be accessible.

**Problem:** LLM API calls fail  
**Solution:** Verify `JEVRAG_DASHSCOPE_API_KEY` is set correctly in `backend/.env`

---

## Performance Notes

**On this system (Windows + WSL2):**
- llama.cpp build: ~10-15 minutes
- Backend startup: ~15 seconds (once caches are warm; a first boot adds the one-time embedding-model download)
- Hybrid pipeline query: ~41 s p50, measured on the 2-core sandbox (run `16814bd5`, see [results.md](results.md)); this 12-core workstation came in at 17.7 s p50 for the `base` arm of Layer-2 run `4ec32592` ([testbench-results-layer2-full9-r2.md](testbench-results-layer2-full9-r2.md))
- Full benchmark suite: ~2-4 hours

**Optimization tips:**
- Close memory-heavy applications during benchmark runs
- Don't run frontend build concurrently with benchmarks
- Consider increasing `JEVRAG_JEV_SCORE_N_CTX` if you have RAM to spare

---

## References

- Main setup guide: [docs/setup.md](setup.md)
- Architecture: [docs/architecture.md](architecture.md)
- Benchmarking: [docs/benchmarking.md](benchmarking.md)
- Project status: [docs/dev/project-status-2026-09-30.md](dev/project-status-2026-09-30.md)
