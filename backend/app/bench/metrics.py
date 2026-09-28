"""Deterministic retrieval metrics — no LLM involved.

Definitions (standard; see docs/benchmarking.md for sources):
- hit@k      1 if any of the top-k chunks is relevant (from a gold file)
- MRR@k      1 / rank of the first relevant chunk (TREC-QA / Voorhees 1999)
- recall@k   distinct gold files found in top-k / total gold files
- ndcg@k     DCG/IDCG with binary relevance (BeIR's primary metric)

Relevance is chunk-level (chunk's source file in gold_files); recall is file-level
(a gold file counts once even if several of its chunks are retrieved).
"""
from __future__ import annotations

import math
from statistics import mean, quantiles


def _dcg(rels: list[int]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def retrieval_metrics(ranked_files: list[str], gold_files: list[str]) -> dict:
    """Compute metrics for one query.

    ranked_files: filenames of the context chunks IN FINAL ORDER (rank 1 first;
                  may contain duplicates when several chunks come from one file).
    gold_files:   ground-truth files containing the answer.

    Relevance is FILE-LEVEL: a gold file counts as relevant only at its FIRST
    occurrence in the ranking (duplicates don't inflate DCG — this keeps
    ndcg <= 1.0 when several chunks of the same gold file are retrieved).
    """
    gold = set(gold_files)
    n = len(ranked_files)
    seen: set[str] = set()
    rels: list[int] = []
    for f in ranked_files:
        if f in gold and f not in seen:
            seen.add(f)
            rels.append(1)
        else:
            rels.append(0)

    hit1 = 1 if n >= 1 and rels[0] == 1 else 0
    hit4 = 1 if any(rels[:4]) else 0
    hit10 = 1 if any(rels[:10]) else 0

    mrr = 0.0
    for i, r in enumerate(rels[:10]):
        if r == 1:
            mrr = 1.0 / (i + 1)
            break

    found = {f for f in ranked_files[:4] if f in gold}
    recall4 = len(found) / len(gold) if gold else 0.0
    found10 = {f for f in ranked_files[:10] if f in gold}
    recall10 = len(found10) / len(gold) if gold else 0.0

    ideal = [1] * min(len(gold), 10)
    ndcg10 = _dcg(rels[:10]) / _dcg(ideal) if ideal else 0.0

    return {
        "hit1": hit1, "hit4": hit4, "hit10": hit10,
        "mrr": round(mrr, 4), "recall4": round(recall4, 4),
        "recall10": round(recall10, 4), "ndcg10": round(ndcg10, 4),
    }


def pct(values: list[float], p: float) -> float:
    """Percentile without numpy (p in 0..100)."""
    if not values:
        return 0.0
    if len(values) == 1:
        return round(float(values[0]), 3)
    qs = quantiles(values, n=100, method="inclusive")
    idx = max(0, min(99, int(round(p)) - 1))
    return round(float(qs[idx]), 3)


def agg_retrieval(per_query: list[dict]) -> dict:
    """Mean over query-level retrieval metric dicts (skips queries with no gold)."""
    non_empty = [q for q in per_query if q]
    if not non_empty:
        return {}
    keys: list[str] = []
    for q in non_empty:
        for k in q:
            if k not in keys:
                keys.append(k)
    out = {}
    for k in keys:
        vals = [q[k] for q in non_empty if q.get(k) is not None]
        if vals:
            out[k] = round(mean(vals), 4)
    return out


def brier(probabilities: list[float], outcomes: list[bool]) -> float:
    """Brier score for the sufficiency gate's calibration vs answerability."""
    if not probabilities:
        return 0.0
    return round(sum((p - (1.0 if o else 0.0)) ** 2 for p, o in zip(probabilities, outcomes)) / len(probabilities), 4)
