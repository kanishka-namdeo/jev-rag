# v2 Ablation — Passage Battery Attribution (full 6-scenario re-run)

**Purpose.** The full v2 run ([`0314ac0a`](benchmark-results.md), battery ON) showed hybrid
v2 losing to traditional by 20.8pp, with the per-passage screening battery implicated
by the loss taxonomy (8/16 losses: injection false-positives dropping gold passages;
3 more: all-evidence drops). A preliminary finance-only ablation (run `e98907aa`,
below) confirmed the mechanism on one scenario. This document records the decisive
question: **does disabling the battery alone recover v1-level hybrid numbers across
ALL six scenarios?**

- **Run**: `bf05f585-7a73-45f9-9b32-e2dd766981e8` · all 6 scenarios · 48 questions × 2
  arms · 0 errors · 75.0 min · judge kimi-k2.5 (independent family, self-test **8/8**) ·
  generator qwen3.7-plus (same as both prior full runs) · config records
  `passage_battery: false`, everything else at production defaults (effort routing,
  corrective retry, citation verification on; `jev_no_retrieval_threshold=0.9`)
- **Same endpoint, same model ids, same judge as runs `0314ac0a` and `9d894b6c`** —
  cross-run comparability is as good as it gets with a drifting cloud endpoint
  (see *Confounds*).

## Result — headline

| pooled (n=48) | traditional | hybrid v2 (battery ON, `0314ac0a`) | **hybrid v2 (battery OFF, this run)** | hybrid v1 (`9d894b6c`) |
|---|---|---|---|---|
| correctness | 83.3% → 87.5% | 62.5% | **92.7%** | 93.8% |
| faithfulness | 100% | 95.8% | **100%** | 99.0% |
| pairwise win rate | — | 29.2% (4W/24L/20T) | **56.3% (9W/3L/36T)** | 58.3% (4W/0L/44T*) |
| position consistency | — | 75% | **91.7%** | 100% |
| over-abstention (answerable) | 14.0% | 39.5% | **4.7%** | 2.3% |
| fabrication (unanswerable) | 0% | 20% (1/5) | **0%** | 0% |

\* v1 pairwise counts from a different judge session; read within-run only.

**Within-run verdict (the controlled comparison): hybrid battery-off 92.7% vs
traditional 87.5% = +5.2pp**, pairwise 9W/3L/36T. Statistics: McNemar exact
p = 0.375 (4 hybrid-only vs 1 trad-only binary wins); Wilcoxon p = 0.222
(rank-biserial +0.52); paired bootstrap 95% CI of Δcorrectness **[−3.1, +14.6]** —
includes zero. Same honest label as v1's +8.3pp: **directionally positive trend,
underpowered at n=48, not an established win.**

## Per-scenario — does it recover v1-level numbers everywhere?

| scenario | v1 t/h | v2-ON hybrid | **v2-OFF hybrid (this)** | v2-OFF within-run Δ | recovered? |
|---|---|---|---|---|---|
| finance | 75 / 100 | 50 | **100** | **+25.0** | ✅ exactly v1 |
| policy | 87.5 / 87.5 | 50 | **100** | **+12.5** | ✅ exceeds v1 |
| distractor | 75 / 87.5 | 50 | **87.5** | **+12.5** | ✅ exactly v1 |
| outofscope | 75 / 87.5 | 87.5 | **87.5** | −12.5† | ✅ matches v1 (trad moved, see below) |
| techdocs | 100 / 100 | 75 | **87.5** | ±0.0 | ◐ partial (v1 = 100; trad also fell to 87.5) |
| multilingual | 100 / 100 | 62.5 | **93.75** | −6.2 | ◐ mostly (residual gap) |

† outofscope *traditional* scored 75% in the v1 run and 100% here with identical
code (cloud drift, documented below); the hybrid matches its v1 absolute number.
**4/6 scenarios recover v1-level hybrid numbers exactly or better; the remaining
two recover most of the gap.**

## What the remaining losses are made of (3 pairwise losses, 2 binary)

1. **Rerank demotes gold below top-4** — hybrid hit@4 95.4% vs traditional 100%
   (2 questions). Without the battery, the reranker's misses are no longer masked
   by re-injection; rerank lift is now slightly negative (nDCG@10 −0.059), the
   same known v1-era failure mode (t2-style). The corrective retry compensates on
   correctness but not on every question.
2. **Judge noise at the abstention boundary** — o5: both arms abstained nearly
   identically; judge scored traditional 1.0, hybrid 0.0 (same phenomenon as
   t2/o2 in run `0314ac0a`; the v1 run scored the same traditional abstention 0.0).
3. **One partial answer** — m5 (Friday hours + last entry): hybrid 0.5 vs
   traditional 1.0.

The **4 hybrid wins**: d4, f3, f6, p3 — all cases where traditional over-abstained
and the hybrid's retry loop answered correctly. Over-abstention (answerable):
traditional 4/43 = 9.3% vs hybrid 2/43 = 4.7%.

## Fast-path remediation confirmed

The `jev_no_retrieval_threshold` 0.5 → 0.9 change (shipped after `0314ac0a`) is
validated by this run: **o6 — the fabrication case ("ideal roasting temperature",
answered from parametric knowledge at threshold 0.5) — now properly abstains**;
o1–o8 all score 1.0 correctness including the unanswerable ones. Zero fabrications,
zero misroutes (p7 answered correctly this time).

## Latency & cost (within-run only)

Hybrid p50 58.3s vs traditional 16.7s (3.5×) — the corrective-retry loop plus
gate/verify/citation calls, on a day when the cloud endpoint streamed ~17s p50
for the traditional arm's single-pass answers. Cost $0.0017/q vs $0.0015/q.
No new latency was introduced by this ablation (battery off *saves* one
round-trip vs `0314ac0a`'s 92.6s p50).

## Confounds & objectivity disclosures

1. **Cloud behavior drift affects the traditional arm too** (identical code):
   traditional moved 85.4% (v1 run) → 83.3% (`0314ac0a`) → 87.5% (this run);
   outofscope traditional 75% → 62.5% → 100%. Cross-run comparisons of EITHER
   arm mix endpoint drift with pipeline changes; the within-run Δ is the
   controlled comparison.
2. **Single run, single judge family, n=48.** The +5.2pp is underpowered
   (6 discordant pairs); the CI spans −3.1 to +14.6pp. Direction is consistent
   across pairwise (9W/3L), binary (4:1), and continuous readouts — magnitude
   is uncertain.
3. **Judge variance on abstention scoring** (o5) is worth roughly 1 question in
   both directions at this n.
4. **Verbosity probe** (judge style-bias check): Spearman(len, correctness) =
   −0.36 traditional / −0.25 hybrid — both negative, no asymmetric length
   favoritism toward the hybrid.
5. Protocol unchanged and audited: independent judge family (kimi-k2.5 vs
   qwen3.7-plus generators), blind absolute scoring, MT-Bench position swap
   (inconsistent → tie), temperature 0, JSON verdicts, 8-case canary self-test
   (8/8 this run).

## Conclusion

**Attribution confirmed at full scale**: the passage battery — not the rest of
v2 — caused the −20.8pp regression of run `0314ac0a`. With one flag flipped
(`JEVRAG_HYBRID_PASSAGE_BATTERY=false`), the same seven-slot v2 pipeline scores
+5.2pp over traditional within-run (n.s.), recovers v1-level hybrid numbers in
4/6 scenarios exactly-or-better and most of the gap in the other two, restores
faithfulness to 100%, over-abstention to 4.7%, and eliminates the fabrication
case. The shipped defaults (battery off, no_retrieval ≥ 0.9) are now backed by
a full-scale ablation rather than a single-scenario study. The battery's
*concept* remains sound for a calibrated decision model; re-enabling requires
per-corpus threshold calibration against labeled data (see
`docs/hybrid-design.md`).

## Preliminary study (superseded by this run)

The finance-only ablation (run `e98907aa`, battery OFF, same session as
`0314ac0a`) first isolated the mechanism: hybrid 50% → 100%, pairwise 4W/0L/4T,
reproducing the v1-era finance result exactly. It motivated the default flip and
this full re-run. Machine-readable artifacts:
`backend/data/bench_exports/e98907aa-b7b5-48b5-ae20-14216a4db0e8.json` and
`backend/data/bench_exports/bf05f585-7a73-45f9-9b32-e2dd766981e8.json` ·
analysis via `scripts/analyze_bench_run.py`.
