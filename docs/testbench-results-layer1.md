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

**Interpretation (2026-09-28, truncated-CE scores):** the top-1 cross-encoder score is a
*weak but usable* escalation signal — the reranker over-scoring "relevant-looking"
passages is visible at wiki2 (pass rate 1.00 while gold-in-top4 is only 0.50) and
musique. At the time the shipped default stayed θ=0.5: it escalated ~17% of questions,
concentrated on the hard scenarios (musique 56%, squad 20%), which matches the design
intent (easy questions stay fast; hard questions get the agentic path). The Youden
optimum (θ*=0.987 → escalate 47%) would trade ~3x hard-path cost for +1.1pp
gate accuracy — rejected on cost. **This conclusion is superseded by the 2026-10-03
re-run below**: the 0.987 optimum was an artifact of scoring 400-char prefixes, and the
0.5→0.6 move (2026-10-01, to match the template) is now the measured optimum — see
[θ provenance](configuration.md) and the re-run section. Layer-2's H-GATE arms measure
whether this choice was right end-to-end.

## Consequence for the pipeline

- v3 retrieval default confirmed: **retrieval_mode=hybrid_rrf + rerank_mode=cross**.
- jev rerank demoted to a testbench arm only (already the v3 design).
- Embedding swap rejected; MiniLM stays.
- ~~gate_score_threshold stays 0.5 (calibrated operating point, documented above).~~
  Superseded: 0.6 since 2026-10-01, now the measured Youden optimum on full-chunk
  scores — see the re-run below.

## Re-run 2026-10-03: full-chunk cross-encoder input (`rerank_char_limit=0`)

The 09-28 run above scored 400-char passage prefixes — the cross-encoder shared the jev
decision-latency knob. Since 2026-10-03 the CE scores full chunk text (new
`JEVRAG_RERANK_CHAR_LIMIT`, default 0). Re-ran all 7 arms × 98 questions offline, same
code otherwise. Raw per-question rows:
`backend/data/testbench/retrieval_eval_fullchunk_2026-10-03.json` (untracked data dir).

| arm | recall@4 | hit@1 | MRR@10 | nDCG@10 | Δrecall@4 vs rrf-cross | McNemar p |
|---|---|---|---|---|---|---|
| **rrf-cross (v3 default)** | 0.853 | **0.939** | **0.964** | **0.861** | — | — |
| rrf (no rerank) | **0.855** | 0.898 | 0.936 | 0.838 | +0.002 [−0.025, +0.028] | 0.688 |
| dense-cross | 0.854 | 0.939 | 0.962 | 0.861 | +0.001 [−0.032, +0.031] | 0.688 |
| bge-cross (5 scen.) | 0.831 | 0.929 | 0.955 | 0.841 | −0.022 [−0.054, +0.005] | 1.000 |
| dense | 0.815 | 0.827 | 0.895 | 0.795 | −0.038 [−0.082, +0.003] | 0.581 |
| rrf-jev | 0.800 | 0.847 | 0.889 | 0.793 | −0.053 [−0.103, −0.005] | 0.607 |
| bm25 | 0.787 | 0.878 | 0.920 | 0.795 | **−0.066 [−0.102, −0.032]** | **0.012** |

Every 09-28 finding replicates in direction: BM25 alone significantly worse on recall;
jev noul the weakest reranker (musique 0.656 → 0.448 again; wiki2 0.766 → 0.703);
fusion adds nothing over the reranker; embedding swap rejected (now on all 5 scenarios,
still n.s.). Precision moved up a notch on full chunks (hit@1 0.918 → 0.939, MRR@10
0.942 → 0.964) — evidence lives past char 400 often enough to matter.

### Gate calibration on full-chunk scores

n=98, positive rate 0.684. Youden-optimal θ* = **0.630** (J = 0.20), accuracy at
θ* = **0.7245**, Brier = **0.269**, ECE = 0.273.

Operating table (pass = easy path):

| θ | pass rate | acc | FN | FP |
|---|---|---|---|---|
| 0.3 | 89% | 0.714 | 4 | 24 |
| 0.5 | 89% | 0.714 | 4 | 24 |
| **0.6 (shipped)** | **88%** | **0.724** | **4** | **23** |
| 0.7 | 86% | 0.704 | 6 | 23 |
| 0.9 | 80% | 0.684 | 10 | 21 |
| 0.987 (old θ*) | 53% | 0.561 | 29 | 14 |

**Interpretation:** the 0.987 optimum from 09-28 was an artifact of truncated inputs —
prefix scores pile up near 1.0, so Youden had to go to the extreme to separate anything.
On full-chunk scores the distribution spreads and the optimum lands at 0.63, i.e. the
shipped 0.6 **is** the measured operating point (same accuracy 0.7245 as at θ*). It also
lifts the gate above the trivial never-escalate baseline (0.724 vs 0.684) — on truncated
scores the shipped point sat *below* it (0.673 vs 0.70). Still weak-but-usable (Brier
0.269 ≈ Layer-2 coverage Brier 0.271 for `base` — the two layers now agree), and the
escalation rate (~12%) is thinner than the 09-28 design intent (~17%); whether that costs
end-to-end accuracy is a Layer-2 question for the next full run, not this table.
