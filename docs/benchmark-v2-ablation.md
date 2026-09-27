# v2 Ablation — Passage Battery Attribution (finance scenario)

**Purpose.** The full v2 run ([`0314ac0a`](benchmark-results.md)) showed hybrid v2 losing
to traditional by 20.8pp, with the per-passage screening battery implicated by the loss
taxonomy (8/16 losses involved injection false-positives dropping gold passages). This
ablation isolates the battery's contribution: the finance scenario re-run with one flag
changed — `JEVRAG_HYBRID_PASSAGE_BATTERY=false` — everything else at production defaults
(effort routing, corrective retry, citation verification all on), same judge, same
corpora, same session (cloud conditions matched).

- **Run**: `e98907aa-b7b5-48b5-ae20-14216a4db0e8` · finance scenario · 8 questions × 2
  arms · 0 errors · judge kimi-k2.5 (self-test 8/8) · config records
  `passage_battery: false`
- **Baseline being ablated against**: finance in run `0314ac0a` (same scenario,
  battery ON), hybrid 50.0% / traditional 75.0%.

## Result

| finance scenario | traditional | hybrid v2 (battery ON, run 0314ac0a) | hybrid v2 (battery OFF, this run) | hybrid v1 (run 9d894b6c) |
|---|---|---|---|---|
| correctness | 75.0% | 50.0% | **100.0%** | 100.0% |
| faithfulness | 100% | 100% | 100% | 100% |
| hit@4 | 100% | 88% | 100% | 100% |
| nDCG@10 | 0.990 | 0.728 | 0.795 | 0.795 |
| pairwise | — | 37.5% (1W/3L/4T) | **75.0% (4W/0L/4T)** | 75.0% (4W/4T) |
| latency p50 | 18.1s | 88.8s | 61.2s | 32.4s* |

\* v1 latency from a faster-cloud session; within this run hybrid-off-battery is 61.2s
(3× traditional — the local rerank + gate + retry + citation calls) with no battery
round-trip.

**Statistics (n=8 — treat as indicative only)**: McNemar exact p = 0.5 (2 discordant
pairs, both hybrid wins); Wilcoxon p = 0.5; bootstrap CI of Δ [+0.00, +0.625]. The
sample is far too small for significance — the value here is **attribution**, not
proof of superiority.

## What this establishes

1. **The battery caused the finance regression.** Removing it (only change) recovers
   hybrid correctness 50% → 100% under matched conditions, reproducing the v1-era
   result exactly. The specific mechanism (verified per-question in run 0314ac0a):
   the injection noul scored 0.93–0.97 on ordinary earnings prose at the 0.9 drop
   threshold, deleting the gold Northwind/Avalanche passages from context.
2. **The rest of v2 is not implicated in finance losses.** With the battery off, the
   remaining slots (effort routing, rerank, sufficiency gate + corrective retry,
   citation verification) produce a clean 8/8 — including the questions the battery
   destroyed (f1, f4, f5 all correct here).
3. **Why this justifies the default flip.** `hybrid_passage_battery` now ships
   `false` (see `backend/app/config.py` comment). The battery's *concept* — TypeSafe's
   classifying-RAG cookbook — remains sound for a properly calibrated decision model;
   with the 0.8B stand-in its absolute thresholds are miscalibrated on two of three
   nouls (injection saturates on prose, evidence collapses on near-duplicates).
   Re-enabling requires per-corpus threshold calibration against labeled data.

## Caveats

- n=8, one scenario — the finance corpus (near-identical earnings numbers) is both
  where the battery did its damage and where v1's hybrid excelled; other scenarios'
  losses (multilingual, policy, distractor) had partially different mechanisms
  (conflict-flag hedging, evidence drops, one effort misroute) that this ablation
  does not individually isolate.
- Judge noise is present in both directions at this sample size (position
  consistency 87.5%).
- The o6 fabrication (no_retrieval fast path answering from parametric knowledge) is
  NOT addressed by this ablation; the separate remediation is the
  `jev_no_retrieval_threshold` 0.5 → 0.9 default change.

_Machine-readable artifact:
`backend/data/bench_exports/e98907aa-b7b5-48b5-ae20-14216a4db0e8.json` · analysis
via `scripts/analyze_bench_run.py`._
