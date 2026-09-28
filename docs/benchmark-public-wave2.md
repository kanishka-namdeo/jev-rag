# Benchmark Results — Public RAG Benchmarks, Wave 2 (TriviaQA + 2WikiMultiHopQA + MuSiQue)

- **Run**: `bcfdd120-e05c-4e47-b15e-37cf119b9652` — three further popular public RAG
  benchmarks (hybrid v2 battery-off vs traditional)
- **Status**: completed · 96 result rows · 48 questions × 2 systems · 0 errors
- **Duration**: ~125 min (resumable driver, sandbox-reaper-proof chained windows)
- **Judge**: kimi-k2.5 (independent family; self-test agreement **100%**, 8/8 canaries)
- **Config**: identical audited protocol to run `4dc6c46e` — top_k retrieve/use = 10/4 ·
  generators qwen3.7-plus / qwen3.6-plus (hybrid routing) · sufficiency threshold 0.5 ·
  battery OFF, corrective retry / best-of-n / citation-verify ON · both arms same corpus,
  same questions, blind judge with position-swapped pairwise

Wave 1 (SQuAD + HotpotQA, run `4dc6c46e`) is documented in
[`benchmark-public.md`](benchmark-public.md). Together the two waves cover **five
canonical public benchmarks, 98 seeded questions**.

## Headline (all three wave-2 scenarios pooled)

| metric | traditional | hybrid (Jev) |
|---|---|---|
| binary correctness (judge ≥ 0.5) | 43.8% | **56.2%** (+12.5pp, McNemar exact p=0.21, n.s.) |
| mean correctness (judge) | 0.427 | 0.521 (Wilcoxon p=0.35, n.s.; CI −5 to +24pp) |
| faithfulness (judge) | 98.9% | 100% |
| recall@4 (file-level) | 69.5% | 75.8% |
| hit@4 | 98% | 98% |
| over-abstention (answerable Qs) | 60.4% | 41.7% |
| latency p50 | ~21s | ~87s |
| cost / query | $0.0018 | $0.0020 |
| pairwise win rate | — | 61.5% (W14/T31/L3, pos-consistency 83%) |

Statistics are not significant at n=48 — the direction is consistent across both
multi-hop benchmarks, not a single-scenario fluke.

## Per-scenario results

### MuSiQue-Ans (validation sample) (`musique`) — 16 questions, compositional multi-hop

- **traditional**: correctness **12.5%** · over-abstention 13/16 · recall@4 47.4% · p50 26.2s
- **hybrid**: correctness **37.5%** · over-abstention 9/16 · recall@4 **60.4%** (+13pp) · p50 108.6s
- **pairwise**: 5W/2L/9T (56%)
- The hardest benchmark in the suite (adversarial, topically-related distractors by
  construction). The traditional arm collapses: 4 context slots rarely hold the 2–4
  scattered gold paragraphs, and the generator honestly abstains. The hybrid's multistep
  subquery decomposition gathers evidence across hops (recall@4 +13pp) and its corrective
  retry converts abstentions into answers.

### 2WikiMultiHopQA (validation sample) (`wiki2`) — 16 questions, structured + text evidence

- **traditional**: correctness **43.8%** · over-abstention 12/16 · recall@4 67.2% · p50 17.9s
- **hybrid**: correctness **56.2%** · over-abstention 8/16 · recall@4 **76.6%** (+9.4pp) · p50 96.3s
- **pairwise**: 6W/1L/9T (56%)
- Same mechanism as HotpotQA (+18pp in wave 1): multi-hop evidence gathering under hard
  distractors. Includes the structured (subject | relation | object) triple evidence the
  dataset is known for — both pipelines handle it as plain text.

### TriviaQA (rc.wikipedia validation sample) (`triviaqa`) — 16 questions, single-hop open-domain

- **traditional**: correctness **75.0%** · recall@4 93.8% · p50 20.5s
- **hybrid**: correctness **75.0%** · recall@4 90.6% (−3.1pp) · p50 63.6s
- **pairwise**: 3W/0L/13T (59%)
- A dead tie at exactly the same mean correctness. Retrieval is saturated for both arms
  (94% recall@4), so the Jev decision layer has nothing to add — the same regime as SQuAD
  (wave 1, −12pp), minus the gate false-negative losses. The Jev rerank even trades a
  little recall (−3.1pp) on already-saturated single-hop retrieval, at 3× the latency.

## Five-benchmark cross-wave reading (98 public questions)

| benchmark | hop style | n | traditional | hybrid | Δ |
|---|---|---|---|---|---|
| HotpotQA dev-distractor | multi-hop (distractor) | 25 | 66% | **84%** | **+18pp** |
| MuSiQue-Ans val | multi-hop (compositional) | 16 | 12.5% | **37.5%** | **+25pp** |
| 2WikiMultiHopQA val | multi-hop (structured) | 16 | 43.8% | **56.2%** | **+12.4pp** |
| TriviaQA rc.wiki val | single-hop (open-domain) | 16 | **75%** | 75% | 0pp |
| SQuAD v1.1 dev | single-hop (article) | 25 | **82%** | 70% | **−12pp** |
| **pooled** | | **98** | **59.2%** | **66.8%** | **+7.6pp** |

- **Multi-hop subset (57 Q)**: traditional 44.7% vs hybrid 63.2% — **+18.4pp**. The hybrid
  advantage is consistent across all three multi-hop benchmarks and all three mechanisms
  (distractor-style, structured-evidence, compositional), driven by recall@4 gains of
  +9 to +16pp from multistep subquery decomposition.
- **Single-hop subset (41 Q)**: traditional 79.3% vs hybrid 72.0% — **−7.3pp**. With
  retrieval saturated (92–94% recall@4 both arms), the decision layer adds latency and
  occasional gate false-negatives, and removes nothing.
- The pattern matches the internal-suite finding (finance/techdocs/policy gains,
  outofscope-neutral) and generalizes it: **the hybrid architecture pays exactly where
  evidence is scattered across documents, and costs where one document suffices.**

## Loss / win taxonomy (wave 2)

- **12 of 14 hybrid pairwise/correctness wins**: traditional abstained, hybrid answered
  correctly — the corrective-retry loop recovering evidence-starved refusals (same
  mechanism as the HotpotQA wins in wave 1).
- **Hybrid losses** (mq12, w210, w26): sufficiency-gate false negatives with
  **gold files already retrieved** (P(sufficient) = 0.03–0.05 with the gold passage
  top-ranked) — the absolute-threshold miscalibration, now confirmed on public data for
  the fourth time. One further loss (tq4) is judge-boundary noise on two abstentions.
- **Notable artifact** (tq4, both arms): chunk-level retrieval filled all 4 context slots
  with chunks of the *same* gold file (boxing.md ×4), leaving no room for the rest of the
  article — both pipelines then failed to extract the answer. A diversity/dedup aware
  top-k would benefit both arms on long evidence pages.

## Sufficiency-gate calibration (hybrid arm)

| scenario | gate accuracy | Brier | mean P(sufficient) |
|---|---|---|---|
| triviaqa (single-hop) | 87.5% | 0.093 | 0.77 |
| wiki2 (multi-hop) | 31.2% | 0.534 | 0.33 |
| musique (multi-hop) | 37.5% | 0.521 | 0.37 |
| pooled | 52.1% | 0.383 | 0.49 |

The gate is well-calibrated on single-hop public data but badly under-confident on
multi-hop questions (mean P 0.33–0.37 on fully answerable questions) — it systematically
underestimates sufficiency when evidence spans several documents. The corrective-retry
loop currently rescues most of these; wave 1's lesson (relative signals usable,
absolute thresholds not portable across data regimes) now extends to the multi-hop
regime. Internal suite calibration remains 82–92%.

## Reading (objective)

1. Wave 2 strengthens the multi-hop result from one benchmark to three: hybrid wins
   +12 to +25pp on every multi-hop public benchmark tested, with the win mechanism
   (recall@4 lift from subquery decomposition + retry-recovered abstentions) visible in
   the per-question data.
2. The single-hop result is now two-for-two: TriviaQA ties (retrieval saturated, no room
   to help) and SQuAD lost (gate false-negatives). The honest claim is regime-dependent,
   not universal.
3. Pooled across all five public benchmarks the hybrid is +7.6pp (66.8% vs 59.2%),
   not significant at these sample sizes; the multi-hop subset (+18.4pp) is the
   consistent, mechanistically-explained effect.
4. Cost is a wash (~$0.002/query either arm); latency is the real price (p50 ~87s vs
   ~21s pooled, ~1.5–4× depending on scenario).
5. Same caveats as wave 1: small seeded samples (16–25 questions per benchmark),
   file-level retrieval yardstick, one judge family (position-swapped, self-tested
   8/8), no claim of leaderboard comparability with full-scale published numbers.

## Reproducing

```bash
# raw parquet -> scenarios (merge semantics keep wave-1 corpora verbatim)
cd backend && .venv/bin/python scripts/build_public_scenarios.py
# two-arm run (resumable; see backend/scripts/bench_resume.py)
.venv/bin/python scripts/bench_resume.py --scenarios triviaqa,wiki2,musique \
    --label "public RAG benchmarks wave 2"
# analysis
.venv/bin/python ../scripts/analyze_bench_run.py <run_id> --db sqlite:////home/z/my-project/backend/data/app.db
.venv/bin/python ../scripts/analyze_per_scenario.py <run_id>
```

Raw provenance (dataset, URL, split size, seed, strategy) is baked into
`backend/app/bench/corpora/public_benchmarks.json`.
