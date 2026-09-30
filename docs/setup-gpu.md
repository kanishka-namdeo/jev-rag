# GPU Acceleration Setup

> **TL;DR**: GPU acceleration works for `jev-score` (llama.cpp) on both WSL2 and native Linux. The embedder and cross-encoder (ONNX Runtime) fall back to CPU in WSL2 due to GPU virtualization limitations, but work on GPU in native Linux. All fallbacks are graceful — performance degrades but functionality is preserved.

This guide covers GPU acceleration for Jev-RAG's three local inference components: **jev-score** (llama.cpp), **embedder** (fastembed/ONNX), and **cross-encoder** (ONNX).

## Quick Status Table

| Component | Native Linux | WSL2 | Code Location |
|-----------|-------------|------|---------------|
| jev-score (llama.cpp) | ✅ GPU | ✅ GPU | `models/jev-style/build/jev-score` |
| Embedder (fastembed/ONNX) | ✅ GPU | ⚠️ CPU fallback | `backend/app/rag/retriever.py:65-80` |
| Cross-encoder (ONNX) | ✅ GPU | ⚠️ CPU fallback | `backend/app/rag/crossenc.py:160-180` |

## GPU-Accelerated Components

### 1. jev-score (llama.cpp)

**Status**: ✅ GPU acceleration works in WSL2 and native Linux

Built with CUDA support via `GGML_CUDA=ON`. Automatically detects and uses GPU when available.

**Verification**:
```bash
# Check if CUDA is linked
ldd models/jev-style/build/jev-score | grep cuda

# Expected output:
# libcudart.so.12 => /lib/x86_64-linux-gnu/libcudart.so.12
# libcuda.so.1 => /usr/lib/wsl/lib/libcuda.so.1 (WSL2)
```

**Performance**: ~2-3x faster inference on GPU vs CPU.

### 2. Embedder (fastembed/ONNX)

**Status**: ⚠️ GPU acceleration works in native Linux, falls back to CPU in WSL2

Configured to use `CUDAExecutionProvider` with automatic CPU fallback. See `backend/app/rag/retriever.py:65-70`.

**Requirements**:
- `onnxruntime-gpu` package (CUDA 12 compatible version)
- cuDNN 9.x matching CUDA version
- Native Linux or Docker (WSL2 not supported due to GPU virtualization limitations)

### 3. Cross-Encoder (ONNX)

**Status**: ⚠️ GPU acceleration works in native Linux, falls back to CPU in WSL2

Configured to use `CUDAExecutionProvider` with automatic CPU fallback. See `backend/app/rag/crossenc.py:165-169`.

Same requirements as embedder.

## WSL2 GPU Limitation

### The Problem

ONNX Runtime's CUDA provider does **not** work with WSL2's GPU virtualization layer. While `nvidia-smi` shows the GPU in WSL2, ONNX Runtime fails with:

```
CUDA failure 100: no CUDA-capable device is detected
```

### Root Cause

WSL2 uses a paravirtualized GPU driver (`/dev/dxg`) that provides basic CUDA support for tools like `nvidia-smi` and llama.cpp, but lacks the full CUDA runtime environment required by ONNX Runtime. This is a known limitation of WSL2's GPU virtualization architecture.

### Impact

- **jev-score**: Works on GPU in WSL2 (uses llama.cpp with CUDA)
- **Embedder**: Falls back to CPU in WSL2
- **Cross-encoder**: Falls back to CPU in WSL2

The fallback is graceful—performance degrades but functionality is preserved.

### Workarounds

1. **Use native Linux** (recommended for full GPU acceleration)
2. **Use Docker with GPU passthrough** (nvidia-docker on native Linux)
3. **Accept CPU fallback** (embedder and cross-encoder are small models, CPU performance is acceptable)

## Setup Instructions

### Native Linux (Ubuntu 22.04/24.04)

#### 1. Install CUDA Toolkit

```bash
# Check current CUDA version
nvcc --version

# Install CUDA 12.x (if not present)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get install -y cuda-toolkit-12-x
```

#### 2. Install cuDNN

```bash
# Install cuDNN 9.x for CUDA 12.x
sudo apt-get install -y cudnn9-cuda-12
```

#### 3. Install onnxruntime-gpu

```bash
cd backend

# Activate virtual environment
source .venv/bin/activate

# Install CUDA 12 compatible onnxruntime-gpu
pip install onnxruntime-gpu --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/
```

#### 4. Verify GPU Availability

```bash
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
# Expected: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

#### 5. Run GPU Test

```bash
python backend/scripts/gpu_test.py
```

Expected output:
```
Testing jev-score...
  ✓ jev-score responded in X.XXXs
  Info: {'backend': 'gguf', 'model': 'jev-style-0.8b-decision-v3', ...}

Testing embedder...
  ✓ Embedder loaded and encoded in X.XXXs
  Query embedding dim: 384
  Document embeddings: 10 x 384

Testing cross-encoder reranker...
  ✓ Cross-encoder scored in X.XXXs
  Scores: ['X.XXXX', 'X.XXXX', 'X.XXXX']

Checking ONNX Runtime providers...
  Available providers: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

### WSL2 (Windows Subsystem for Linux)

#### 1. Install CUDA Toolkit

```bash
# Same as native Linux
sudo apt-get install -y cuda-toolkit-12-x
```

#### 2. Install cuDNN

```bash
# Same as native Linux
sudo apt-get install -y cudnn9-cuda-12
```

#### 3. Install onnxruntime-gpu

```bash
# Same as native Linux (but GPU won't work for ONNX)
pip install onnxruntime-gpu --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/
```

#### 4. Verify GPU Status

```bash
python backend/scripts/gpu_test.py
```

Expected output (note the fallback warnings):
```
Testing jev-score...
  ✓ jev-score responded in X.XXXs  # GPU works

Testing embedder...
  [WARNING] CUDA execution failed, falling back to CPU
  ✓ Embedder loaded and encoded in X.XXXs  # CPU fallback

Testing cross-encoder reranker...
  [WARNING] CUDA execution failed, falling back to CPU
  ✓ Cross-encoder scored in X.XXXs  # CPU fallback

Checking ONNX Runtime providers...
  Available providers: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
  # CUDA provider is available but doesn't work in WSL2
```

## Performance Comparison

| Component | CPU (2 cores) | GPU (RTX 2070 Super) | Speedup |
|-----------|---------------|----------------|---------|
| jev-score | ~1.5s/query | ~0.5s/query | 3x |
| Embedder (10 docs) | ~0.3s | ~0.1s | 3x |
| Cross-encoder (3 docs) | ~0.15s | ~0.05s | 3x |

**Note**: GPU acceleration provides ~2-3x speedup for local inference. The cloud LLM calls (qwen3.7-plus) dominate overall latency (~2-5s), so GPU acceleration reduces total pipeline time by ~10-20%.

## Troubleshooting

### "CUDA failure 100: no CUDA-capable device is detected"

**Cause**: WSL2 GPU virtualization limitation or missing CUDA drivers

**Solution**:
- In WSL2: Accept CPU fallback (expected behavior)
- In native Linux: Verify CUDA installation with `nvidia-smi` and reinstall drivers

### "Failed to load library libonnxruntime_providers_cuda.so"

**Cause**: Missing cuDNN or CUDA libraries

**Solution**:
```bash
# Install cuDNN
sudo apt-get install -y cudnn9-cuda-12

# Verify CUDA libraries
ldconfig -p | grep cuda
```

### "onnxruntime-gpu not found"

**Cause**: Wrong package installed

**Solution**:
```bash
# Uninstall CPU version
pip uninstall onnxruntime

# Install GPU version with CUDA 12 support
pip install onnxruntime-gpu --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/
```

## Verification Commands

Run these to verify GPU status for all components:

```bash
# 1. Check GPU status for all components (comprehensive test)
cd backend
.venv/bin/python scripts/gpu_test.py

# 2. Verify jev-score CUDA linking
ldd models/jev-style/build/jev-score | grep cuda
# Expected: libcudart.so.12, libcuda.so.1

# 3. Check CUDA availability in ONNX Runtime
.venv/bin/python -c "import onnxruntime as ort; print(ort.get_available_providers())"
# Expected (native Linux): ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
# Expected (WSL2): Same list, but CUDA provider won't actually work

# 4. Run backend tests to confirm everything works
.venv/bin/python -m pytest tests/ -v
```

## Dependencies

Known dependency versions for GPU acceleration:

- `onnxruntime-gpu==1.18.1` with CUDA 12 support
- `cudnn9-cuda-12` for ONNX Runtime
- `protobuf` ≥ 7.36.2 (to match chromadb requirements)

## References

- [ONNX Runtime CUDA Execution Provider](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [WSL2 GPU Support Documentation](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [llama.cpp CUDA Build](https://github.com/ggerganov/llama.cpp/blob/master/docs/build.md#cuda)
- [fastembed GPU Acceleration](https://qdrant.github.io/fastembed/installation/)
