"""Check ONNX Runtime providers and CUDA availability."""
import sys
print("Python:", sys.version)

# Try importing the full onnxruntime package
try:
    import onnxruntime as ort
    print("\n=== onnxruntime import OK ===")
    print("Package path:", ort.__path__)
    
    # Try to get available providers
    try:
        providers = ort.get_available_providers()
        print("Available providers:", providers)
        
        if "CUDAExecutionProvider" in providers:
            print("\n✓ CUDA Execution Provider is AVAILABLE")
        else:
            print("\n✗ CUDA Execution Provider is NOT available")
            print("  Only CPU providers found:", [p for p in providers if "CPU" in p])
    except AttributeError as e:
        print("ERROR: get_available_providers() not found:", e)
        print("This suggests onnxruntime-gpu didn't install correctly")
        
except ImportError as e:
    print("ERROR: Failed to import onnxruntime:", e)
    sys.exit(1)

# Try importing CUDA provider directly
print("\n=== Checking CUDA provider library ===")
try:
    from onnxruntime.capi import onnxruntime_pybind11_state
    print("✓ onnxruntime_pybind11_state imported successfully")
except ImportError as e:
    print("✗ Failed to import pybind11_state:", e)
    print("  This usually means CUDA libraries are missing or incompatible")

# Check if CUDA provider .so exists
import os
capi_path = os.path.dirname(__file__)
if not capi_path:
    import onnxruntime.capi
    capi_path = os.path.dirname(onnxruntime.capi.__file__)

cuda_so = os.path.join(capi_path, "libonnxruntime_providers_cuda.so")
if os.path.exists(cuda_so):
    print(f"✓ CUDA provider library exists: {cuda_so}")
else:
    print(f"✗ CUDA provider library NOT found at: {cuda_so}")
