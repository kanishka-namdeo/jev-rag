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


# ================================================================================
# RAGAS-style LLM-based metrics (context precision, context recall)
# ================================================================================
# These metrics use an LLM judge to evaluate retrieval quality beyond deterministic
# file-level metrics. They decompose the retrieval→generation pipeline and diagnose
# WHERE failures occur (retrieval coverage vs ranking quality).
#
# Implementation follows RAGAS 0.4.3 definitions:
# - Context Precision: Are relevant chunks ranked highly? (diagnoses reranking)
# - Context Recall: Was all needed context retrieved? (diagnoses retrieval coverage)
#
# Reference: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/


def context_precision(
    question: str,
    reference: str,
    retrieved_contexts: list[str],
    judge_fn: callable,
) -> float:
    """Compute context precision using LLM judge.

    For each retrieved chunk, judge if it's useful for answering the question.
    Compute average precision (AP) over the ranked list.

    Args:
        question: The user's question
        reference: Ground-truth reference answer
        retrieved_contexts: List of retrieved context chunks (in rank order)
        judge_fn: Function that takes (system_prompt, user_prompt) and returns dict

    Returns:
        Average precision score (0.0 to 1.0)

    Interpretation:
        1.0 = all relevant chunks ranked at the top
        0.5 = relevant chunks scattered throughout
        0.0 = no relevant chunks retrieved
    """
    if not retrieved_contexts:
        return 0.0

    system_prompt = """You are an impartial judge evaluating retrieval quality.

For each retrieved context, determine if it contains information useful for answering the question.

Respond with ONLY a JSON object: {"useful": true} or {"useful": false}"""

    verdicts = []
    for ctx in retrieved_contexts:
        user_prompt = f"""QUESTION: {question}

REFERENCE ANSWER: {reference}

RETRIEVED CONTEXT:
{ctx}

Is this context useful for answering the question?"""

        result = judge_fn(system_prompt, user_prompt)
        useful = result.get("useful", False) if result else False
        verdicts.append(1 if useful else 0)

    # Compute average precision
    precisions = []
    n_relevant = 0
    for i, v in enumerate(verdicts, 1):
        if v == 1:
            n_relevant += 1
            precisions.append(n_relevant / i)

    # Average Precision = (1/n_relevant) * sum(precisions)
    # If no relevant contexts found, return 0.0
    return round(sum(precisions) / n_relevant, 4) if n_relevant > 0 else 0.0


def context_recall(
    question: str,
    reference: str,
    retrieved_contexts: list[str],
    judge_fn: callable,
) -> float:
    """Compute context recall using LLM judge.

    Decompose the reference answer into atomic claims, then check how many
    claims are supported by the retrieved context.

    Args:
        question: The user's question
        reference: Ground-truth reference answer
        retrieved_contexts: List of retrieved context chunks
        judge_fn: Function that takes (system_prompt, user_prompt) and returns dict

    Returns:
        Recall score (0.0 to 1.0)

    Interpretation:
        1.0 = all claims in reference are supported by retrieved context
        0.5 = half the claims are supported
        0.0 = no claims are supported

    Edge cases:
        - Empty reference → return 1.0 (nothing to recall)
        - Empty context → return 0.0 (nothing retrieved)
    """
    if not reference or not reference.strip():
        return 1.0  # nothing to recall
    if not retrieved_contexts:
        return 0.0  # nothing retrieved

    # Step 1: Decompose reference into atomic claims
    decompose_system = """You are an impartial assistant that breaks down answers into atomic factual claims.

Extract each distinct factual claim from the answer. Each claim should be a single, verifiable fact.

Respond with ONLY a JSON object: {"claims": ["claim1", "claim2", ...]}"""

    decompose_user = f"""Break down this answer into atomic factual claims:

QUESTION: {question}

ANSWER: {reference}"""

    decompose_result = judge_fn(decompose_system, decompose_user)
    claims = decompose_result.get("claims", []) if decompose_result else []

    if not claims:
        return 0.0

    # Step 2: Check each claim against retrieved context
    context_text = "\n\n---\n\n".join(retrieved_contexts)

    check_system = """You are an impartial judge evaluating factual support.

Determine if the given claim is supported by the retrieved context.

A claim is "supported" if the context contains information that directly or indirectly confirms the claim.
A claim is "not supported" if the context doesn't mention it or contradicts it.

Respond with ONLY a JSON object: {"supported": true} or {"supported": false}"""

    supported_count = 0
    for claim in claims:
        check_user = f"""CLAIM: {claim}

RETRIEVED CONTEXT:
{context_text}

Is this claim supported by the context?"""

        check_result = judge_fn(check_system, check_user)
        if check_result and check_result.get("supported", False):
            supported_count += 1

    return round(supported_count / len(claims), 4)
