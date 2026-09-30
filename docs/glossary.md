# Glossary

Welcome! This glossary defines the jargon you'll encounter in the jev-rag docs. If you're new here, start with the **TL;DR** below, then explore the sections that match what you're working on.

**TL;DR — New here? Start with:** RAG, System One/Two, Hybrid Pipeline, Escalation Gate

---

## 🧠 Core Concepts

**RAG (Retrieval-Augmented Generation)**  
A pattern where an LLM retrieves relevant documents before generating an answer, grounding responses in your data instead of parametric memory. Jev-rag implements two RAG pipelines: traditional (retrieve → generate) and hybrid (retrieve → decide → generate → verify).  
→ [architecture.md](architecture.md), [benchmarking.md](benchmarking.md)

**System One**  
Fast, intuitive decision-making — in jev-rag, a local 0.8B model that makes typed, calibrated decisions (rerank, route, verify) without generating prose. Based on [Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) by TypeSafe AI.  
→ [hybrid-design.md](hybrid-design.md), [rag-upgrade-2026.md](rag-upgrade-2026.md)

**System Two**  
Slow, deliberative reasoning — in jev-rag, the cloud LLM (qwen3.7-plus) that writes the final cited answer. System One decides *how* to answer; System Two *writes* the answer.  
→ [hybrid-design.md](hybrid-design.md), [architecture.md](architecture.md)

**Hybrid Pipeline**  
The jev-augmented RAG pipeline: shared retrieval stack → escalation gate → easy path (one LLM call) or hard path (decompose → multi-step retrieval → best-of-2 → citation verification). Adds guardrails on questions that need them.  
→ [hybrid-design.md](hybrid-design.md), [rag-upgrade-2026.md](rag-upgrade-2026.md)

**Jev**  
TypeSafe AI's closed-weights "System One" decision model — answers typed questions with calibrated probabilities (Choice, Score, Noul), never generates text. Jev-rag uses the open-source [Jev-Style-0.8B](https://huggingface.co/chaoliangUNSW/Jev-Style-0.8B-Decision-v3-GGUF) via the [jev-style](https://github.com/lawrence3699/jev-style) package.  
→ [hybrid-design.md](hybrid-design.md), [README.md](../README.md)

---

## 🔍 Retrieval

**BM25**  
A lexical retrieval algorithm that scores documents by term frequency, inverse document frequency, and document length. Jev-rag uses BM25 alongside dense embeddings to rescue entity/keyword lookups that semantic search misses.  
→ [architecture.md](architecture.md), [testbench-results-layer1.md](testbench-results-layer1.md)

**Dense Embedding**  
A neural network that maps text to a fixed-length vector (384-dim in jev-rag) capturing semantic meaning. Jev-rag uses `paraphrase-multilingual-MiniLM-L12-v2` via fastembed (ONNX, CPU).  
→ [architecture.md](architecture.md), [benchmarking.md](benchmarking.md)

**Cross-Encoder Reranker**  
A model that scores (query, passage) pairs to rerank retrieval candidates. Jev-rag uses `Xenova/ms-marco-MiniLM-L-6-v2` (149M params, ONNX CPU) — dominates 0.5B generative rerank on quality per dollar.  
→ [architecture.md](architecture.md), [testbench-results-layer1.md](testbench-results-layer1.md)

**RRF (Reciprocal Rank Fusion)**  
A method to combine multiple retrieval rankings (e.g., BM25 + dense) by summing reciprocal ranks. Jev-rag uses RRF with k=60 to fuse lexical and semantic retrieval.  
→ [architecture.md](architecture.md), [testbench-results-layer1.md](testbench-results-layer1.md)

**nDCG@10 (Normalized Discounted Cumulative Gain)**  
A retrieval metric that measures ranking quality — how well relevant documents are ranked high, discounted by position. Binary file-level relevance in jev-rag; a gold file counts once at first occurrence.  
→ [benchmarking.md](benchmarking.md), [testbench-results-layer1.md](testbench-results-layer1.md)

**MRR@10 (Mean Reciprocal Rank)**  
A retrieval metric: the average of 1/rank for the first relevant document in each query's top-10. Higher is better; 1.0 means the first result is always relevant.  
→ [benchmarking.md](benchmarking.md), [testbench-results-layer1.md](testbench-results-layer1.md)

---

## 📊 Statistics & Evaluation

**McNemar's Test**  
A paired statistical test for binary outcomes (correct/incorrect on the same questions). Jev-rag uses exact McNemar (two-sided binomial on discordant pairs) to compare traditional vs hybrid pipelines.  
→ [benchmarking.md](benchmarking.md), [testbench-design.md](testbench-design.md), [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md)

**Bootstrap Confidence Interval**  
A resampling method (50k samples, seed 42 in jev-rag) to estimate the uncertainty of a metric delta. Reported as 95% CI — if it includes 0, the difference is not statistically significant.  
→ [benchmarking.md](benchmarking.md), [testbench-design.md](testbench-design.md)

**Brier Score**  
A calibration metric for probabilistic predictions: mean squared error between predicted probability and actual outcome (0 or 1). Lower is better; 0.0 is perfect calibration. Jev-rag uses it to measure gate calibration quality.  
→ [benchmarking.md](benchmarking.md), [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md), [testbench-results-hgate.md](testbench-results-hgate.md)

**ECE (Expected Calibration Error)**  
Measures how well predicted probabilities match actual frequencies across confidence bins. Lower is better; 0.0 is perfect calibration. Jev-rag reports ECE for the escalation gate.  
→ [testbench-results-hgate.md](testbench-results-hgate.md), [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md)

**BH-FDR (Benjamini-Hochberg False Discovery Rate)**  
A multiple-testing correction that controls the expected proportion of false positives across a family of hypotheses. Jev-rag applies BH-FDR across the testbench arm family (H-GATE, H-RERANK, etc.).  
→ [testbench-design.md](testbench-design.md), [testbench-results-hgate.md](testbench-results-hgate.md)

**Wilcoxon Signed-Rank Test**  
A non-parametric paired test for graded outcomes (e.g., correctness scores 0–1). Jev-rag uses it with rank-biserial effect size when McNemar is inappropriate.  
→ [benchmarking.md](benchmarking.md), [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md)

---

## 🏗️ Architecture

**Escalation Gate**  
The decision point that routes questions to the easy path (one LLM call) or hard path (decompose → multi-step retrieval → best-of-2). In v3, the gate uses **score-features** (top-1 rerank score, margin, mean) instead of a Jev absolute judgment.  
→ [hybrid-design.md](hybrid-design.md), [rag-upgrade-2026.md](rag-upgrade-2026.md)

**Score-Feature Gate**  
The v3 escalation gate: calibrated retrieval scores (top-1 cross-encoder score, top1−top2 margin, top-k mean, count-above-floor) decide whether a question needs the hard path. Threshold θ is calibrated on labeled eval data using Youden J.  
→ [hybrid-design.md](hybrid-design.md), [rag-upgrade-2026.md](rag-upgrade-2026.md), [testbench-results-layer1.md](testbench-results-layer1.md)

**Noul (Probability of Truth)**  
A Jev primitive: P(statement is true). Used for reranking (P(passage is relevant)), sufficiency (P(context is sufficient), removed in v3), and citation verification (P(citation is supported)).  
→ [hybrid-design.md](hybrid-design.md)

**Choice**  
A Jev primitive: pick one option from a list. Used for effort routing (no_retrieval / single_pass / multi_step) and best-of-2 selection (faithful vs planted candidate).  
→ [hybrid-design.md](hybrid-design.md)

**Score**  
A Jev primitive: rubric rating (e.g., 1–5). Used for pointwise reranking in v2 (replaced by cross-encoder in v3) and optional testbench arms.  
→ [hybrid-design.md](hybrid-design.md)

**H-GATE**  
A pre-declared hypothesis in the testbench: "the score-feature gate improves accuracy vs never-escalating." Tested with arms: base (features gate), gate-none (never escalate), always-hard (always escalate), oracle-gate (perfect retry decision). Full-power results: [testbench-results-hgate.md](testbench-results-hgate.md).  
→ [testbench-design.md](testbench-design.md), [testbench-results-hgate.md](testbench-results-hgate.md), [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md)

---

## Further Reading

- **Architecture overview:** [architecture.md](architecture.md)
- **Hybrid pipeline design:** [hybrid-design.md](hybrid-design.md), [rag-upgrade-2026.md](rag-upgrade-2026.md)
- **Benchmarking methodology:** [benchmarking.md](benchmarking.md)
- **Results:** [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md), [testbench-results-hgate.md](testbench-results-hgate.md)
