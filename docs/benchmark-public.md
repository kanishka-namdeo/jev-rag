# Benchmark Results — Traditional vs Hybrid (Jev) RAG

- **Run**: `4dc6c46e-a566-4134-ab9d-a59a653564e5` — public RAG benchmarks: SQuAD v1.1 + HotpotQA dev-distractor (hybrid v2 battery-off vs traditional)
- **Status**: completed · 100 result rows · 50 questions × 2 systems
- **Duration**: 94.5 min
- **Judge**: kimi-k2.5 (independent family; self-test agreement **100%**)
- **Config**: top_k retrieve/use = 10/4 · generators qwen3.7-plus / qwen3.6-plus (hybrid routing) · sufficiency threshold 0.5

## Headline (all scenarios pooled)

| metric | traditional | hybrid (Jev) |
|---|---|---|
| correctness (judge) | 74.0% | 77.0% |
| faithfulness (judge) | 100.0% | 97.9% |
| hit@4 | 94% | 94% |
| MRR@10 | 0.883 | 0.890 |
| nDCG@10 | 0.807 | 0.867 |
| recall@4 | 82% | 90% |
| latency p50 | 19.4s | 64.2s |
| latency p95 | 48.1s | 129.0s |
| cost / query | $0.0018 | $0.0015 |
| pairwise win rate | — | 55.0% (W13/T29/L8, pos-consistency 86%) |

## Hybrid-only intelligence

| metric | value |
|---|---|
| Jev rerank lift — hit@4 | +0.0% |
| Jev rerank lift — MRR@10 | +0.017 |
| Jev rerank lift — nDCG@10 | +0.051 |
| sufficiency gate accuracy | 72.0% (Brier 0.223, n=50) |
| mean P(sufficient) | 0.647 |
| mean verification (groundedness) | 0.776 |

## Abstention & hallucination (out-of-scope scenario)

| metric | traditional | hybrid |
|---|---|---|
| proper abstention (unanswerable) | — | — |
| fabrication rate (unanswerable) | — | — |
| over-abstention (answerable) | 24% | 16% |

## Per-scenario results

### HotpotQA (dev distractor sample) (`hotpotqa`) — 25 questions

- **traditional**: correctness **66.0%** · faithfulness **100.0%** · hit@4 **96%** · MRR **0.867** · nDCG@10 **0.709** · p50 21.3s · cost $0.0018/q
- **hybrid**: correctness **84.0%** · faithfulness **96.8%** · hit@4 **96%** · MRR **0.860** · nDCG@10 **0.814** · p50 78.1s · cost $0.0013/q
- **pairwise**: hybrid win rate 64.0% (W10/T12/L3)

### SQuAD v1.1 (dev sample) (`squad`) — 25 questions

- **traditional**: correctness **82.0%** · faithfulness **100.0%** · hit@4 **92%** · MRR **0.900** · nDCG@10 **0.905** · p50 18.1s · cost $0.0018/q
- **hybrid**: correctness **70.0%** · faithfulness **99.0%** · hit@4 **92%** · MRR **0.920** · nDCG@10 **0.920** · p50 63.6s · cost $0.0016/q
- **pairwise**: hybrid win rate 46.0% (W3/T17/L5)

## Per-question detail

| scenario | q | system | correctness | faithfulness | verdict | hit@4 | model | latency |
|---|---|---|---|---|---|---|---|---|
| hotpotqa | hp1 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 61.5s |
| hotpotqa | hp1 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 11.8s |
| hotpotqa | hp10 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 42.5s |
| hotpotqa | hp10 | traditional | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 24.5s |
| hotpotqa | hp11 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 88.8s |
| hotpotqa | hp11 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 37.0s |
| hotpotqa | hp12 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 40.4s |
| hotpotqa | hp12 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 13.9s |
| hotpotqa | hp13 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 43.3s |
| hotpotqa | hp13 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 10.8s |
| hotpotqa | hp14 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 95.2s |
| hotpotqa | hp14 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 15.5s |
| hotpotqa | hp15 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 47.2s |
| hotpotqa | hp15 | traditional | 1.00 | 1.00 | abstained | 1 | qwen3.7-plus | 23.9s |
| hotpotqa | hp16 | hybrid | 1.00 | 0.70 | answered | 1 | qwen3.7-plus | 111.5s |
| hotpotqa | hp16 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 8.7s |
| hotpotqa | hp17 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 38.3s |
| hotpotqa | hp17 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 23.9s |
| hotpotqa | hp18 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 48.5s |
| hotpotqa | hp18 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 27.1s |
| hotpotqa | hp19 | hybrid | 0.00 | 1.00 | answered | 1 | qwen3.7-plus | 103.1s |
| hotpotqa | hp19 | traditional | 0.00 | 1.00 | answered | 1 | qwen3.7-plus | 15.9s |
| hotpotqa | hp2 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 89.6s |
| hotpotqa | hp2 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 19.0s |
| hotpotqa | hp20 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 51.7s |
| hotpotqa | hp20 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 23.3s |
| hotpotqa | hp21 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 43.2s |
| hotpotqa | hp21 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 18.3s |
| hotpotqa | hp22 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 52.9s |
| hotpotqa | hp22 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 29.2s |
| hotpotqa | hp23 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 139.1s |
| hotpotqa | hp23 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 15.9s |
| hotpotqa | hp24 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 79.5s |
| hotpotqa | hp24 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 39.3s |
| hotpotqa | hp25 | hybrid | 0.00 | 0.50 | answered | 1 | qwen3.7-plus | 86.3s |
| hotpotqa | hp25 | traditional | 0.50 | 1.00 | answered | 1 | qwen3.7-plus | 48.4s |
| hotpotqa | hp3 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 65.3s |
| hotpotqa | hp3 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 19.5s |
| hotpotqa | hp4 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 85.1s |
| hotpotqa | hp4 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 25.3s |
| hotpotqa | hp5 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 114.1s |
| hotpotqa | hp5 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 33.3s |
| hotpotqa | hp6 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 46.3s |
| hotpotqa | hp6 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 23.5s |
| hotpotqa | hp7 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 89.1s |
| hotpotqa | hp7 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 21.3s |
| hotpotqa | hp8 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 78.1s |
| hotpotqa | hp8 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 18.4s |
| hotpotqa | hp9 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 83.5s |
| hotpotqa | hp9 | traditional | 1.00 | 1.00 | abstained | 1 | qwen3.7-plus | 19.2s |
| squad | sq1 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 39.7s |
| squad | sq1 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 12.9s |
| squad | sq10 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 63.6s |
| squad | sq10 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 32.1s |
| squad | sq11 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 101.4s |
| squad | sq11 | traditional | 0.00 | 1.00 | answered | 1 | qwen3.7-plus | 28.0s |
| squad | sq12 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 143.2s |
| squad | sq12 | traditional | 0.50 | 1.00 | answered | 1 | qwen3.7-plus | 65.0s |
| squad | sq13 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 53.5s |
| squad | sq13 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 11.5s |
| squad | sq14 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 55.1s |
| squad | sq14 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 23.2s |
| squad | sq15 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 46.4s |
| squad | sq15 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 13.9s |
| squad | sq16 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 50.0s |
| squad | sq16 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 19.9s |
| squad | sq17 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 54.4s |
| squad | sq17 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 12.4s |
| squad | sq18 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 52.1s |
| squad | sq18 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.6s |
| squad | sq19 | hybrid | 1.00 | 0.75 | answered | 1 | qwen3.7-plus | 64.6s |
| squad | sq19 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 18.1s |
| squad | sq2 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 47.0s |
| squad | sq2 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.7s |
| squad | sq20 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 127.2s |
| squad | sq20 | traditional | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 33.5s |
| squad | sq21 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 46.6s |
| squad | sq21 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 10.0s |
| squad | sq22 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 130.5s |
| squad | sq22 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 70.1s |
| squad | sq23 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 43.5s |
| squad | sq23 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.3s |
| squad | sq24 | hybrid | 0.50 | 1.00 | answered | 1 | qwen3.7-plus | 67.2s |
| squad | sq24 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 25.9s |
| squad | sq25 | hybrid | 0.00 | 1.00 | answered | 1 | qwen3.7-plus | 86.9s |
| squad | sq25 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 19.6s |
| squad | sq3 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 49.0s |
| squad | sq3 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 12.8s |
| squad | sq4 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 113.5s |
| squad | sq4 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 47.7s |
| squad | sq5 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 94.2s |
| squad | sq5 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 12.8s |
| squad | sq6 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 90.0s |
| squad | sq6 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 12.4s |
| squad | sq7 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 49.6s |
| squad | sq7 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 18.5s |
| squad | sq8 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 96.6s |
| squad | sq8 | traditional | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 19.6s |
| squad | sq9 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 63.7s |
| squad | sq9 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 13.0s |

_Methodology: docs/benchmarking.md · machine-readable artifact: backend/data/bench_exports/4dc6c46e-a566-4134-ab9d-a59a653564e5.json · generated 2026-09-28T12:56:20.645596+00:00._
---

## Statistical analysis (paired, within-run)

Computed by `scripts/analyze_bench_run.py` (Dietterich 1998; Demšar 2006):

| test | statistic | p | significant (α=0.05) |
|---|---|---|---|
| McNemar exact (binary @0.5; 4 trad-only vs 5 hybrid-only) | Δ +2.0pp | 1.000 | no |
| McNemar exact (binary @0.75; 3 trad-only vs 5 hybrid-only) | Δ +4.0pp | 0.727 | no |
| Wilcoxon signed-rank (correctness, n=50) | rank-biserial +0.27 | 0.426 | no |
| Paired bootstrap 95% CI of Δcorrectness | [+0.03] point est | — | CI [−0.08, +0.14] includes 0 |
| Faithfulness (1.000 vs 0.979) | rank-biserial −1.0 | 0.109 | no |

Verbosity probe (Spearman answer-length vs correctness): traditional −0.40 /
hybrid −0.49 — the judge penalizes long answers in both arms symmetrically; no
pro-hybrid verbosity favoritism.

## Loss / win taxonomy (questions with |Δcorrectness| > 0.4)

**Traditional wins (8 pairwise; 5 by margin >0.4):**

| mechanism | questions | what happened |
|---|---|---|
| **Sufficiency-gate false negative → abstention** | sq5, sq12 (2) | Both arms retrieved the SAME gold article (top-4 identical files). The 0.8B gate scored P(sufficient) = 0.02 / 0.19 on jargon-dense Wikipedia prose (magnetic stratigraphers; computational-complexity reduction) → hybrid abstained while traditional answered correctly from the same context. The same absolute-threshold failure mode the passage battery showed (run `0314ac0a`), now via the gate. |
| **Judge-boundary generation losses** | sq24, sq25, hp25 (3) | Hybrid answered with both entities when the reference named one ("Genghis Khan and Timur" vs "Timur" → 0.5), missed a specific phrase ("may no longer exist"), or was scored 0 while a semantically-equivalent answer (hp25, American Samoa) got 0.5 for the traditional arm's "not explicitly stated" hedging — judge noise at the boundary cuts both ways. |

**Hybrid wins (13 pairwise; 6 by margin > 0.4 — all on HotpotQA):**

Every large hybrid win (hp4, hp5, hp11, hp12, hp14) is a **traditional
over-abstention the hybrid recovered**: the traditional arm declined to answer
(9/25 abstentions) while the hybrid's corrective-retry loop answered correctly.
Retrieval also improved: hybrid recall@4 88% vs traditional 72% on the
10-paragraph-per-question distractor contexts — the multi-step retrieval /
rerank / retry machinery earned its cost exactly where evidence is scattered
across two gold articles amid eight distractors.

## Sufficiency-gate calibration (hybrid arm)

| scenario | mean P(sufficient) | questions < 0.5 | abstained | retry recovered |
|---|---|---|---|---|
| squad | 0.657 | 7 | 6 | 1 |
| hotpotqa | 0.638 | 7 | 2 | 5 |

The gate fires "insufficient" equally often in both scenarios (7/25 below 0.5),
but the corrective retry rescued 5/7 on HotpotQA versus 1/7 on SQuAD — single-hop
re-queries retrieve the same passage and re-gate low, so the gate's absolute
miscalibration surfaces as abstention exactly there. Gate accuracy 72%, Brier
0.223 (internal-suite runs: 82–92%, Brier 0.08–0.16).

## Reading (objective)

The hybrid design pays off on **multi-hop distractor-heavy QA** — +18pp
correctness, +16pp recall@4, 64% pairwise win rate — and pays for it with a 3.3×
p50 latency. On **single-hop QA over a clean corpus**, the extra machinery buys
nothing at the retrieval layer (both arms 92% hit@4) and the sufficiency gate's
absolute threshold converts two answerable questions into abstentions, costing
12pp against a leaner traditional pipeline. Pooled: +3pp correctness, 55%
pairwise win rate — directionally positive, statistically indistinguishable at
n=50 (McNemar p=1.0, Wilcoxon p=0.43, bootstrap CI spans zero).

This independently reproduces the suite's standing lesson on public data: the
0.8B decision model is reliable as a *relative* signal (rerank, retry
orchestration) and unreliable as an *absolute* gate (battery thresholds in run
`0314ac0a`, sufficiency threshold here). Both were calibrated on the internal
hand-authored corpora and do not transfer to public Wikipedia-style prose
without held-out tuning.
