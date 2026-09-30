"""GPU acceleration dry-run test."""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.llm.jev_engine import JevEngine
from app.rag.retriever import Embedder
from app.rag.crossenc import CrossEncoderReranker

settings = get_settings()

print("=" * 60)
print("GPU ACCELERATION DRY RUN")
print("=" * 60)

# Test 1: jev-score (llama.cpp with CUDA)
print("\n[1/3] Testing jev-score (llama.cpp with CUDA)...")
try:
    jev = JevEngine(settings)
    jev.load()
    start = time.time()
    result = jev.effort_routing("What is the capital of France?")
    elapsed = time.time() - start
    print(f"  ✓ jev-score responded in {elapsed:.3f}s")
    print(f"  Info: {jev.info()}")
except Exception as e:
    print(f"  ✗ jev-score failed: {e}")

# Test 2: Embedder (fastembed with CUDA)
print("\n[2/3] Testing embedder (fastembed)...")
try:
    embedder = Embedder(settings)
    embedder.load()
    start = time.time()
    query_vec = embedder.embed_query("What is machine learning?")
    doc_vecs = embedder.embed_documents(["Machine learning is a subset of AI.", "The weather is nice."] * 5)
    elapsed = time.time() - start
    print(f"  ✓ Embedder loaded and encoded in {elapsed:.3f}s")
    print(f"  Query embedding dim: {len(query_vec)}")
    print(f"  Document embeddings: {len(doc_vecs)} x {len(doc_vecs[0])}")
except Exception as e:
    print(f"  ✗ Embedder failed: {e}")

# Test 3: Cross-encoder reranker
print("\n[3/3] Testing cross-encoder reranker...")
try:
    reranker = CrossEncoderReranker()
    reranker.load()
    query = "What is machine learning?"
    passages = [
        "Machine learning is a subset of artificial intelligence.",
        "The weather today is sunny and warm.",
        "Deep learning uses neural networks with many layers.",
    ]
    start = time.time()
    scores = reranker.score_pairs(query, passages)
    elapsed = time.time() - start
    print(f"  ✓ Cross-encoder scored in {elapsed:.3f}s")
    print(f"  Scores: {[f'{s:.4f}' for s in scores]}")
except Exception as e:
    print(f"  ✗ Cross-encoder failed: {e}")

# GPU status
print("\n" + "=" * 60)
print("Checking ONNX Runtime providers...")
import onnxruntime as ort
print(f"  Available providers: {ort.get_available_providers()}")
print("=" * 60)
print("DRY RUN COMPLETE")
print("=" * 60)
