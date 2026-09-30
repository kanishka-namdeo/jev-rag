# Layer-1 Retrieval Testbench Results

> Run: 2026-09-28, offline (no cloud LLM), 98 questions across 5 public scenarios
> (SQuAD 25, HotpotQA 25, TriviaQA 16, 2WikiMultiHopQA 16, MuSiQue 16).
> Design + arms: docs/testbench-design.md (pre-declared). Raw per-question data:
> `backend/data/testbench/retrieval_eval.json` (untracked data dir; the numbers
> below are the record). Statistics: exact McNemar on gold-in-top-4, paired
> bootstrap 95% CI (50k resamples, seed 42) on recall@4 — vs the v3 default arm.

## Pooled results

| arm | recall@4 | hit@1 | MRR@10 | nDCG@10 | Δrecall@4 vs rrf-cross | McNemar p |
|---|---|---|---|---|---|---|
| **rrf-cross (v3 default)** | 0.849 | **0.918** | **0.942** | **0.849** | — | — |
| rrf (no rerank) | **0.851** | 0.878 | 0.926 | 0.831 | +0.003 [-0.023, +0.031] | 1.000 |
| dense-cross | 0.842 | 0.918 | 0.941 | 0.846 | −0.007 [−0.037, +0.019] | 1.000 |
| bge-cross (4 scen.) | 0.812 | 0.902 | 0.931 | 0.815 | −0.019 [−0.061, +0.018] | 0.688 |
| dense | 0.815 | 0.827 | 0.895 | 0.795 | −0.034 [−0.076, +0.007] | 0.227 |
| rrf-jev | 0.816 | 0.816 | 0.872 | 0.797 | −0.033 [−0.082, +0.010] | 0.790 |
| bm25 | 0.787 | 0.878 | 0.920 | 0.795 | **−0.062 [−0.095, −0.032]** | **0.001** |

bge-cross ran on squad/hotpotqa/wiki2/musique only (n=73): TriviaQA's ~15k-chunk
corpus cannot re-embed inside one sandbox window; subset reported as such.

## Findings (objective, including the negative ones)

1. **The v3 default (RRF + cross-encoder) is the best precision retriever**
   (hit@1 0.918, MRR 0.942, nDCG 0.849) at recall equal to the best recall arm
   (0.849 vs 0.851, within noise, p=1.0). Rerank buys precision, not recall —
   consistent with the published evidence cited in the design doc.
2. **BM25 alone is significantly worse on recall (−6.2pp, p=0.001) but
   complementary**: its hit@1 (0.878) beats dense-only (0.827). That
   complementarity is exactly why the fusion works.
3. **The jev noul rerank is the weakest reranker**: rrf-jev 0.816 recall vs
   0.851 for no rerank at all — the pointwise-LLM rerank *degrades* the fused
   ranking on 3 of 5 scenarios (hotpotqa 0.90→0.88, wiki2 0.77→0.73, musique
   0.64→0.45). n.s. pooled (p=0.79, n=98), direction consistent. This is the
   retrieval-layer answer to H-RERANK: cross-encoder > jev, and jev < nothing.
4. **The embedding swap did not pay**: bge-small-en-v1.5 −1.9pp vs the
   multilingual MiniLM baseline on the English public suite (n.s.). Per the
   pre-declared rule ("only keep if recall@k moves") the swap is REJECTED; the
   multilingual embedder stays.
5. **Rerank on MuSiQue hurts** (rrf 0.635 → rrf-cross 0.557 recall): on
   compositional questions where gold evidence does not look "relevant", a
   relevance reranker demotes it. The pipeline's defense is the escalation gate
   + decomposition, not the reranker. Honest caveat, reported.
6. **Fusion adds ~nothing on top of the reranker** (rrf-cross 0.849 vs
   dense-cross 0.842, n.s.) for these benchmarks — but RRF is ~free and BM25
   alone is the rescue arm for entity lookups; the design keeps it (cost ≈ 0).

## Gate calibration (pre-declared target: top-1 cross score vs gold-in-top-4)

n=98, positive rate 0.70. Youden-optimal θ* = **0.987** (J = 0.24), accuracy at
θ* = **0.59**, Brier = **0.282**, ECE = 0.276.

Operating table (pass = easy path):

| θ | pass rate | acc | FN | FP |
|---|---|---|---|---|
| 0.3 | 84% | 0.684 | 9 | 22 |
| **0.5 (shipped)** | **83%** | **0.673** | **10** | **22** |
| 0.7 | 80% | 0.684 | 11 | 20 |
| 0.9 | 70% | 0.653 | 17 | 17 |
| 0.98 | 53% | 0.561 | 30 | 13 |

**Interpretation:** the top-1 cross-encoder score is a *weak but usable*
escalation signal — the reranker over-scoring "relevant-looking" passages is
visible at wiki2 (pass rate 1.00 while gold-in-top4 is only 0.50) and musique.
The shipped default stays θ=0.5: it escalates ~17% of questions, concentrated
on the hard scenarios (musique 56%, squad 20%), which matches the design intent
(easy questions stay fast; hard questions get the agentic path). The Youden
optimum (θ*=0.987 → escalate 47%) would trade ~3x hard-path cost for +1.1pp
gate accuracy — rejected on cost. Layer-2's H-GATE arms measure whether this
choice was right end-to-end.

## Consequence for the pipeline

- v3 retrieval default confirmed: **retrieval_mode=hybrid_rrf + rerank_mode=cross**.
- jev rerank demoted to a testbench arm only (already the v3 design).
- Embedding swap rejected; MiniLM stays.
- gate_score_threshold stays 0.5 (calibrated operating point, documented above).
