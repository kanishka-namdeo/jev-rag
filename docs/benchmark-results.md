# Benchmark Results — Traditional vs Hybrid (Jev) RAG

Two full runs are documented here:

- **Run `0314ac0a` — hybrid v2 (current)**: the seven-slot single-generator pipeline
  (effort routing, decomposed multi-retrieval, Jev rerank, per-passage screening
  battery, sufficiency gate + corrective retry, best-of-2, citation verification).
  All slots enabled at production defaults. **This is the primary result.**
- **Run `9d894b6c` — hybrid v1 (archived)**: the four-slot pipeline (broad retrieval,
  rerank, sufficiency gate, answer verification). Kept at the bottom for the v1→v2
  comparison; cross-run numbers carry environment variance (see *Confounds*).

## Verdict (stated plainly)

**Hybrid v2 lost to traditional on this benchmark — correctness 62.5% vs 83.3%
(−20.8pp), Wilcoxon p = 0.033, pairwise 4W/24L/20T (29.2% win rate).** The regression
is concentrated in v2's *new* safety screens: the per-passage battery's
prompt-injection noul fired on ordinary earnings/technical prose at 0.91–0.98
(threshold 0.9), dropping gold passages from the context; "no evidence" drops emptied
the context entirely on near-duplicate KB questions; and conflict-blocked passages
pushed the generator into unnecessary abstention. Over-abstention on answerable
questions jumped from 14% (traditional) / 2.3% (v1 hybrid) to **39.5%**.

The v1 result (hybrid +8.3pp over traditional, concentrated in distractor-heavy
scenarios) was not reproduced by v2 — v2 hybrid scored 31.3pp below v1 hybrid
(cross-run comparison, see *Confounds*). Within this run, under identical conditions,
the traditional arm was better.

## Run `0314ac0a` configuration

- 48 questions × 2 systems · 6 scenarios · 0 errors · 98.1 min
- Judge kimi-k2.5 (independent model family from both arms' qwen3.7-plus generator;
  self-test agreement 8/8 = 100%)
- top_k retrieve/use = 10/4 (matched final context budget); sufficiency threshold 0.5
- v2 slots: effort_routing ✓ · passage_battery ✓ · corrective_retry ✓ · best_of_n ✓ ·
  citation_verify ✓
- Engine memory-trimmed for this run (jev-score seq2/out32; bit-identical decisions,
  306 MB saved — see `scripts/verify_jev_runtime_parity.py`)

## Statistical analysis (paired, within-run — the controlled comparison)

Computed by `scripts/analyze_bench_run.py` (Dietterich 1998; Demšar 2006):

| test | statistic | p | significant (α=0.05) |
|---|---|---|---|
| McNemar (exact binomial; 16 trad-only vs 6 hybrid-only wins) | — | 0.052 | no (borderline) |
| Wilcoxon signed-rank (correctness, n=48) | rank-biserial −0.45 | 0.033 | **yes** |
| Paired bootstrap 95% CI of Δcorrectness | [−0.396, −0.021] | — | CI excludes 0 |
| Faithfulness (1.000 vs 0.958) | — | 0.157 | no |

**Reading.** All three tests point the same direction: the hybrid v2 deficit is real
at conventional significance (two of three tests), though McNemar on binary outcomes
is borderline (p=0.052) — with n=48 and 22 discordant pairs the study is underpowered
for effects of this size. The direction is unambiguous; the exact magnitude is
uncertain (Δcorrectness 95% CI spans −0.40 to −0.02).

## Headline (all scenarios pooled)

| metric | traditional | hybrid v2 | Δ (hybrid − trad) |
|---|---|---|---|
| correctness (judge) | 83.3% | 62.5% | **−20.8pp** |
| faithfulness (judge) | 100.0% | 95.8% | −4.2pp |
| hit@4 | 100% | 74% | −26pp |
| MRR@10 | 0.855 | 0.580 | −0.274 |
| nDCG@10 | 0.890 | 0.623 | −0.267 |
| recall@4 | 100% | 74% | −26pp |
| latency p50 | 16.8s | 92.6s | +75.8s |
| latency p95 | 30.3s | 161.4s | +131.1s |
| cost / query | $0.0015 | $0.0019 | +$0.0004 |
| pairwise win rate | — | 29.2% (W4/T20/L24, pos-consistency 75%) | — |

Note: retrieval metrics for the hybrid arm are measured on the **post-battery kept
set**, which is why they collapse — the embedding retrieval itself was healthy
(pooled naive hit@4 before rerank/battery: 100%, matching traditional; see
*Loss taxonomy*).

## Loss taxonomy — where the 16 losses come from

`scripts/diagnose_v2_losses.py` classifies every question where hybrid scored below
traditional (16 losses vs 6 wins):

| mechanism | questions | what happened |
|---|---|---|
| **Injection false positive drops gold passage** | f1, f4, f5, m1, m4, p2, p5, p6 (8) | P(prompt-injection) = 0.91–0.98 on ordinary earnings/technical/museum prose at drop-threshold 0.9 → gold passages removed from context → abstention. On m4 all four kept passages were dropped as "injection". |
| **Evidence false positive empties context** | d2, d6, o2 (3) | P(evidence) ≈ 0.01–0.06 on near-duplicate KB passages (the same low-signal regime where the 0.8B model can't discriminate) → all passages dropped → "(no passages retained)" → abstention. |
| **Conflict flags push hedging** | t2, t6, m5, f1* (3, one overlaps) | "premise contradiction" 0.55–0.81 flags make the generator reason about conflicting evidence instead of answering; answers turn into meta-discussion of the conflict notice. |
| **Effort-routing misroutes answerable question** | p7 (1) | P(no_retrieval) ≥ 0.5 on a look-up policy question → retrieval skipped entirely → abstention. |
| **Judge noise at the abstention boundary** | t2, o2 (2, overlap above) | Both arms abstained identically; judge scored traditional 1.0, hybrid 0.0 (the v1 run scored the same traditional abstention 0.0). |
| Rerank demotes gold below top-4 | t2 (1, overlap) | Gold limits-chunk scored 0.49/0.044 vs architecture 0.697 → gold out of top-4 (same failure as v1's t2). |

\* f1 shows both injection-drop and conflict-flag mechanisms.

The **6 hybrid wins**: f6 and d-scenario questions where the battery correctly
included the gold passage and the traditional arm over-abstained, plus outofscope
questions answered from general knowledge via the no_retrieval fast path (o7 —
see the fabrication discussion below for why this cut both ways).

## Hybrid-only intelligence

| metric | v2 (this run) | v1 (archived run) |
|---|---|---|
| Jev rerank lift — nDCG@10 | **−0.245** | −0.042 |
| sufficiency gate accuracy | 82.2% (Brier 0.164, n=45) | 91.7% (Brier 0.077, n=48) |
| mean P(sufficient) | 0.636 | 0.683 |
| mean verification (groundedness) | 0.619 | 0.798 |

- **Battery actions across the run**: 67 drops (25 injection, 42 evidence),
  45 conflict flags — out of 192 kept-passage evaluations. The screens fire on 58%
  of retained passages; the large majority are false positives.
- **Effort routing**: 43 single_pass, 1 multi_step, 4 no_retrieval. Best-of-2 never
  activated (requires multi_step or post-retry insufficiency; the 21 corrective
  retries mostly ended ≥ 0.5 sufficiency).
- **Corrective retries**: 21/48 questions retried (rewrite + re-retrieve +
  re-screen) — the main driver of the 92.6s p50 alongside cloud latency.
- **Citation verification** (hybrid answers that cited): 54 supports, 3 contradicts,
  6 says_nothing — the citation checker itself behaves sensibly.

## Abstention & hallucination

| metric | traditional | hybrid v2 | hybrid v1 |
|---|---|---|---|
| proper abstention (unanswerable) | 100% (5/5) | 80% (4/5) | 100% |
| fabrication rate (unanswerable) | 0% | **20% (1/5)** | 0% |
| over-abstention (answerable) | 14.0% | **39.5%** | 2.3% |

The single fabrication (o6, "ideal internal temperature for roasting a chicken") came
from the **no_retrieval fast path**: effort routing classified the question as
general-knowledge, and the generator answered from parametric knowledge ("165°F") —
correct as cooking advice, but the scenario contract requires corpus-grounded
abstention, and the judge labeled it fabricated. The same fast path won o7 (reference
value matched general knowledge) and lost p7 (answerable policy question misrouted).
On out-of-scope factual questions the fast path is a coin flip against the abstention
contract.

## Confounds & objectivity disclosures

1. **Cloud latency drift (both arms affected).** qwen3.7-plus streamed at 16.8s p50
   this run vs 1.5s in the v1 run five hours earlier (retrieval itself: 12ms). All
   latency and cost comparisons should be read within-run only; the hybrid's p50 is
   92.6s *including* the slow cloud calls and 21 retry loops.
2. **Cloud behavior drift affects cross-run correctness too.** The traditional arm —
   identical code — scored 85.4% in the v1 run and 83.3% here; its outofscope score
   moved 100% → 62.5% (longer, less abstaining answers). Therefore the v1→v2 hybrid
   comparison (93.8% → 62.5%) mixes pipeline changes with endpoint drift; the
   within-run comparison (−20.8pp) is the controlled one.
3. **Judge noise at the abstention boundary.** t2 and o2 produced identical
   abstention behavior in both arms with opposite judge scores (traditional 1.0 /
   hybrid 0.0). Position consistency 75%; the pairwise judge swapped-inconsistent
   verdicts resolved to ties (20 ties include these).
4. **Judge model.** kimi-k2.5, independent family from the generator (qwen3.7-plus),
   temperature 0, JSON-only, blind to system identity — self-test 8/8. Verbosity
   probe: Spearman(len, correctness) = −0.37 (traditional) / +0.04 (hybrid) — no
   length favoritism toward the hybrid.
5. **Single run, single judge family, n=48** — treat magnitudes as indicative;
   significance tests above quantify the uncertainty honestly.

## Interpretation (curated, objective)

**What the data says.** The v2 research proposal (TypeSafe cookbook battery,
conflict-blocking, no_retrieval fast path) did **not** survive contact with the
0.8B decision stand-in on these corpora. The screens are conceptually sound but
their operating points are miscalibrated for this model: the injection noul
saturates (0.9+) on legitimate prose, and the evidence noul collapses (≈0.03) on
near-duplicate distractor corpora — the exact regimes where v1's *reranker* (the
same model, used as a relative ranker instead of an absolute gate) was reliable.
This validates the published cautions the design was grounded in: calibrated
absolute thresholds need held-out tuning before gating anything ("Planning-Fails"
/ budget-aware-eval warnings), and hard drops without labeled data are the riskiest
slot (jev-in-the-pipeline §4: gates showed no net gain).

**What still works.** The reranker as a *relative* signal, the sufficiency gate's
direction (82% accuracy even on battery-depleted contexts), citation verification
(63 verdicts, sensible), and honest behavior when context is genuinely absent.
v1 — rerank + gate orchestration only — remains the better hybrid configuration on
this evidence.

**Recommended remediation (knob-level, all shipped):**
- disable the battery by default (`JEVRAG_HYBRID_PASSAGE_BATTERY=false`) or raise
  `JEVRAG_JEV_INJECTION_DROP_THRESHOLD` to ≥ 0.99 (observed false positives reach
  0.98, so 0.99 retains only near-certain catches — at which point honest
  discrimination is unproven and off is the evidence-backed choice);
- raise `JEVRAG_JEV_NO_RETRIEVAL_THRESHOLD` from 0.5 to ≥ 0.9, or restrict the
  fast path to conversational patterns;
- keep effort routing, corrective retry, and citation verification (no measured
  harm; retry loop cost is real but bounded).

An ablation re-run of the finance scenario with the battery disabled is documented
in `docs/benchmark-v2-ablation.md` (run `e98907aa`) — hybrid correctness recovered
50% → 100% with the battery off, attributing the entire finance regression to the
battery's false positives.

## Per-scenario results (run `0314ac0a`)

### Support KB (Needle) (`distractor`) — 8 questions

- **traditional**: correctness **75.0%** · faithfulness **100.0%** · hit@4 **100%** · MRR **0.760** · nDCG@10 **0.820** · p50 21.5s · cost $0.0019/q
- **hybrid**: correctness **50.0%** · faithfulness **100.0%** · hit@4 **62%** · MRR **0.500** · nDCG@10 **0.533** · p50 102.2s · cost $0.0019/q
- **pairwise**: hybrid win rate 31.2% (W1/T3/L4)

### Earnings Reports (`finance`) — 8 questions

- **traditional**: correctness **75.0%** · faithfulness **100.0%** · hit@4 **100%** · MRR **1.000** · nDCG@10 **0.990** · p50 16.7s · cost $0.0015/q
- **hybrid**: correctness **50.0%** · faithfulness **100.0%** · hit@4 **88%** · MRR **0.667** · nDCG@10 **0.728** · p50 88.8s · cost $0.0023/q
- **pairwise**: hybrid win rate 37.5% (W1/T4/L3)

### Lumen Exhibition (`multilingual`) — 8 questions

- **traditional**: correctness **100.0%** · faithfulness **100.0%** · hit@4 **100%** · MRR **0.667** · nDCG@10 **0.753** · p50 19.4s · cost $0.0016/q
- **hybrid**: correctness **62.5%** · faithfulness **100.0%** · hit@4 **50%** · MRR **0.438** · nDCG@10 **0.454** · p50 106.9s · cost $0.0018/q
- **pairwise**: hybrid win rate 12.5% (W0/T2/L6)

### Cooking Corpus + OoS (`outofscope`) — 8 questions

- **traditional**: correctness **62.5%** · faithfulness **100.0%** · hit@4 **100%** · MRR **1.000** · nDCG@10 **1.000** · p50 15.0s · cost $0.0013/q
- **hybrid**: correctness **87.5%** · faithfulness **75.0%** · hit@4 **67%** · MRR **0.667** · nDCG@10 **0.667** · p50 89.0s · cost $0.0017/q
- **pairwise**: hybrid win rate 31.2% (W0/T5/L3)

### Corporate Policies (`policy`) — 8 questions

- **traditional**: correctness **87.5%** · faithfulness **100.0%** · hit@4 **100%** · MRR **1.000** · nDCG@10 **1.000** · p50 16.8s · cost $0.0017/q
- **hybrid**: correctness **50.0%** · faithfulness **100.0%** · hit@4 **88%** · MRR **0.792** · nDCG@10 **0.812** · p50 79.6s · cost $0.0019/q
- **pairwise**: hybrid win rate 31.2% (W1/T3/L4)

### Tech Product Docs (`techdocs`) — 8 questions

- **traditional**: correctness **100.0%** · faithfulness **100.0%** · hit@4 **100%** · MRR **0.792** · nDCG@10 **0.845** · p50 15.5s · cost $0.0012/q
- **hybrid**: correctness **75.0%** · faithfulness **100.0%** · hit@4 **88%** · MRR **0.469** · nDCG@10 **0.570** · p50 89.5s · cost $0.0022/q
- **pairwise**: hybrid win rate 31.2% (W1/T3/L4)

## Per-question detail (run `0314ac0a`)
| scenario | q | system | correctness | faithfulness | verdict | hit@4 | model | latency |
|---|---|---|---|---|---|---|---|---|
| distractor | d1 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 98.7s |
| distractor | d1 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 20.6s |
| distractor | d2 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 104.0s |
| distractor | d2 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.2s |
| distractor | d3 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 153.6s |
| distractor | d3 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 20.6s |
| distractor | d4 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 162.3s |
| distractor | d4 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 29.6s |
| distractor | d5 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 63.2s |
| distractor | d5 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 26.1s |
| distractor | d6 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 100.4s |
| distractor | d6 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 5.4s |
| distractor | d7 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 129.1s |
| distractor | d7 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 22.4s |
| distractor | d8 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 68.2s |
| distractor | d8 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 28.3s |
| finance | f1 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 96.4s |
| finance | f1 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 21.5s |
| finance | f2 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 167.7s |
| finance | f2 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 15.0s |
| finance | f3 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 81.1s |
| finance | f3 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 18.1s |
| finance | f4 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 64.0s |
| finance | f4 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 17.2s |
| finance | f5 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 67.0s |
| finance | f5 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 19.0s |
| finance | f6 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 190.1s |
| finance | f6 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 15.5s |
| finance | f7 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 67.6s |
| finance | f7 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.3s |
| finance | f8 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 117.4s |
| finance | f8 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 13.6s |
| multilingual | m1 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 95.2s |
| multilingual | m1 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 18.3s |
| multilingual | m2 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 131.2s |
| multilingual | m2 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 15.3s |
| multilingual | m3 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 91.0s |
| multilingual | m3 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 24.5s |
| multilingual | m4 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 97.7s |
| multilingual | m4 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 15.9s |
| multilingual | m5 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 159.7s |
| multilingual | m5 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 23.8s |
| multilingual | m6 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 71.2s |
| multilingual | m6 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 7.1s |
| multilingual | m7 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 125.2s |
| multilingual | m7 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 30.1s |
| multilingual | m8 | hybrid | 1.00 | 1.00 | answered | 0 | qwen3.7-plus | 116.1s |
| multilingual | m8 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 20.6s |
| outofscope | o1 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 129.6s |
| outofscope | o1 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 15.6s |
| outofscope | o2 | hybrid | 0.00 | 1.00 | abstained | — | qwen3.7-plus | 90.2s |
| outofscope | o2 | traditional | 1.00 | 1.00 | abstained | — | qwen3.7-plus | 19.5s |
| outofscope | o3 | hybrid | 1.00 | 1.00 | abstained | — | qwen3.7-plus | 96.2s |
| outofscope | o3 | traditional | 1.00 | 1.00 | abstained | — | qwen3.7-plus | 21.9s |
| outofscope | o4 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 64.5s |
| outofscope | o4 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 14.3s |
| outofscope | o5 | hybrid | 1.00 | 1.00 | abstained | — | qwen3.7-plus | 91.8s |
| outofscope | o5 | traditional | 0.00 | 1.00 | abstained | — | qwen3.7-plus | 13.9s |
| outofscope | o6 | hybrid | 1.00 | 0.00 | fabricated | — | qwen3.7-plus | 24.3s |
| outofscope | o6 | traditional | 0.00 | 1.00 | abstained | — | qwen3.7-plus | 16.9s |
| outofscope | o7 | hybrid | 1.00 | 0.00 | answered | 0 | qwen3.7-plus | 24.6s |
| outofscope | o7 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 14.2s |
| outofscope | o8 | hybrid | 1.00 | 1.00 | abstained | — | qwen3.7-plus | 87.9s |
| outofscope | o8 | traditional | 0.00 | 1.00 | abstained | — | qwen3.7-plus | 10.9s |
| policy | p1 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 71.2s |
| policy | p1 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 9.7s |
| policy | p2 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 86.8s |
| policy | p2 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.7s |
| policy | p3 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 64.4s |
| policy | p3 | traditional | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 31.3s |
| policy | p4 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 72.4s |
| policy | p4 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.2s |
| policy | p5 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 90.4s |
| policy | p5 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.9s |
| policy | p6 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 122.7s |
| policy | p6 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 12.9s |
| policy | p7 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 22.8s |
| policy | p7 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 31.6s |
| policy | p8 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 97.9s |
| policy | p8 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 30.5s |
| techdocs | t1 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 93.5s |
| techdocs | t1 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 15.3s |
| techdocs | t2 | hybrid | 0.00 | 1.00 | abstained | 0 | qwen3.7-plus | 85.5s |
| techdocs | t2 | traditional | 1.00 | 1.00 | abstained | 1 | qwen3.7-plus | 6.9s |
| techdocs | t3 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 81.0s |
| techdocs | t3 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 1.7s |
| techdocs | t4 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 60.0s |
| techdocs | t4 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 25.9s |
| techdocs | t5 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 71.4s |
| techdocs | t5 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 10.5s |
| techdocs | t6 | hybrid | 0.00 | 1.00 | abstained | 1 | qwen3.7-plus | 152.6s |
| techdocs | t6 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 15.7s |
| techdocs | t7 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 134.8s |
| techdocs | t7 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 15.9s |
| techdocs | t8 | hybrid | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 135.7s |
| techdocs | t8 | traditional | 1.00 | 1.00 | answered | 1 | qwen3.7-plus | 16.8s |

---

# Archived: Run `9d894b6c` — hybrid v1 (four-slot pipeline)

The v1 pipeline: broad top-10 retrieval → Jev rerank → top-4 → sufficiency gate →
generation (model routing between qwen3.7-plus / qwen3.6-plus) → answer verification.
No passage battery, no conflict blocks, no effort routing, no fast path.

- 48 questions × 2 systems · 0 errors · 31.9 min · judge kimi-k2.5 (self-test 100%)
- **Headline**: hybrid correctness **93.8%** vs traditional **85.4%** (+8.3pp) ·
  faithfulness 99.0% both · latency p50 1.5s → 30.5s · cost $0.0004/q both
- **Statistics (retroactive, `scripts/analyze_bench_run.py`)**: McNemar p = 0.125
  (4 discordant pairs, all favoring hybrid — not significant at n=48); Wilcoxon
  p = 0.046; bootstrap 95% CI of Δ [+0.02, +0.17]. The v1 advantage was directionally
  consistent but underpowered — we reported it as a win at the time; the honest label
  is "positive trend, not established".
- **Where v1 won**: finance 75→100%, distractor 75→87.5%, policy 75→87.5% —
  distractor discrimination via the reranker; over-abstention 14% → 2.3%.
- Machine-readable artifact: `backend/data/bench_exports/9d894b6c-a995-4e14-8a9a-d9b9ce7f77c0.json`.

Read the *Confounds* section before comparing v1 and v2 numbers directly: the cloud
endpoint drifted between the two runs (the traditional arm itself moved 85.4% →
83.3% overall and 100% → 62.5% on outofscope with identical code).
