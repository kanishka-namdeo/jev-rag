"""Benchmarking & evaluation subsystem for the two RAG pipelines.

Modules:
- scenarios: scenario corpora registry + ground-truth QA sets
- metrics:   deterministic retrieval metrics (hit@k, MRR, recall@k, nDCG, rerank lift)
- judge:     LLM-as-a-judge (absolute RAGAS-style scoring + MT-Bench-style pairwise)
- runner:    orchestration: ingest -> run both pipelines -> judge -> aggregate -> persist

Methodology is grounded in RAGAS / DeepEval / MT-Bench conventions — see
docs/benchmarking.md for definitions, sources and fairness protocol.
"""
