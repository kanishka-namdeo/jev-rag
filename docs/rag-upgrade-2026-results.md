# v3 Upgrade Results: Headline Benchmark + H-GATE Ablation

> Objective record of the Layer-2 runs. Every number carries n, the paired
> statistic, and the CI. Run IDs refer to `bench_runs` in the local DB.
> Design + hypotheses: docs/rag-upgrade-2026.md, docs/testbench-design.md.
> Layer-1 (retrieval) results: docs/testbench-results-layer1.md.

## Headline run — upgraded traditional vs upgraded hybrid (v3, both)

Run `16814bd5` (label "v3-upgrade-headline"), 2026-09-28/29, 98 questions, 5
public scenarios, 16 chained resumable windows, **0 errors**. Both arms run the
v3 stack (RRF retrieval + cross-encoder rerank + contextual-prefix chunking);
the A/B isolates the jev-augmented layer (escalation gate → decompose → CRAG
retry → best-of-2 → citation verification).

| | traditional v3 | hybrid v3 | delta |
|---|---|---|---|
| correctness (judge, kimi-k2.5) | 0.617 | **0.668** | +5.1pp, CI [−0.5, +10.7], McNemar b/c = 9/2, p = 0.065 |
| faithfulness | 0.991 | 0.987 | −0.4pp |
| answered / abstained | 63 / 35 | 73 / 25 | over-abstention 35.7% → 25.5% |
| latency p50 | 19.9 s | 40.9 s | 2.06× (was 3× in v2) |
| cost | $0.165 | **$0.148** | hybrid still cheaper |
| pairwise (kimi-k2.5, pos-swap) | — | 14W/4L/80T, 55.1% win rate, consistency 84% | |

### Pre-declared subsets

| subset | trad | hybrid | delta | paired stats |
|---|---|---|---|---|
| **single-hop** (squad+triviaqa, n=41) | 0.805 | **0.902** | **+9.8pp, CI [+2.4, +19.5], Wilcoxon p = 0.048 — significant** | McNemar 5/0 |
| multi-hop (hotpot+wiki2+musique, n=57) | 0.482 | 0.500 | +1.8pp, CI [−5.3, +8.8], p = 0.69 | n.s. |
| squad (n=25) | 0.840 | 0.940 | +10.0pp | |
| triviaqa (n=16) | 0.750 | 0.844 | +9.4pp | |
| hotpotqa (n=25) | 0.800 | 0.780 | −2.0pp | n.s. |
| wiki2 (n=16) | 0.281 | 0.281 | 0.0pp | |
| musique (n=16) | 0.188 | 0.281 | +9.4pp, n.s. | |

### Interpretation (objective)

1. **The v2 single-hop regression is fixed and inverted**: −7.3pp (v2) →
   **+9.8pp significant** (v3). The gate inversion did exactly what the
   literature predicted: with retrieval deciding sufficiency implicitly, the
   hybrid no longer false-negatives easy questions; instead it answers MORE
   than the baseline (over-abstention 35.7% → 25.5%) and gets those answers
   right (verification + retry recover borderline cases).
2. **The multi-hop edge compressed to +1.8pp (n.s.)** — not because the hybrid
   got worse at multi-hop (musique 0.19→0.28, wiki2 flat), but because the
   *traditional arm got much better* (hotpot 0.66→0.80 vs v2 numbers, musique
   0.125→0.19, retrieval recall up across the board — see Layer-1). The
   upgraded baseline lifted the floor; the jev-augmented layer's residual
   multi-hop value on top of a 2026 baseline is ~nil at n=57. This is the
   honest headline: **the modern baseline ate most of the v2 multi-hop win.**
3. **Gate behavior (features mode, θ=0.5)**: escalated 10/98 (10.2%), accuracy
   vs answerability 0.898, Brier 0.103 — versus the v2 jev gate's 72% acc /
   0.38 Brier on the same public suite (run bcfdd120). Of the 10 escalated
   questions, 6 were answered CORRECTLY after escalation (recovered), 4
   abstained (MuSiQue questions whose gold was never retrieved — honest
   failures, not gate errors: the gate was right that something was wrong).
4. **wiki2 remains the failure case for both arms** (0.28): Layer-1 shows the
   cross-encoder over-scoring "relevant-looking" passages there (gold-in-top4
   0.50 while top-1 score passes 1.00). Structural-evidence questions need
   better retrieval, not more gating.

## H-GATE ablation (Layer-2 testbench, stratified subset)

Run `6b58fc40` (label "h-gate subset"), 20 questions (4 per scenario) × 3 arms,
all through the shared orchestrator, 0 errors. n=20 is underpowered by design
(power note in testbench-design.md) — read as direction, not proof.

| arm | corr | 95% CI | abstain | escalation | p50 latency | cost | Δacc vs base |
|---|---|---|---|---|---|---|---|
| **base (features gate, θ=0.5)** | **0.70** | [0.48, 0.85] | 5 | 15% | 41 s | $0.029 | — |
| gate-none (never escalate) | 0.65 | [0.43, 0.82] | 5 | 0% | 41 s | $0.033 | −5pp, CI [−15, 0], p = 1.0 |
| always-hard (always escalate) | 0.60 | [0.39, 0.78] | 7 | 100% | **106 s** | $0.037 | −10pp, CI [−30, +10], p = 0.63 |

Subsets: single-hop (n=8) base **0.875** vs gate-none 0.75 vs always-hard
0.625; multi-hop (n=12) identical 0.583 across arms. Per-question
disagreements (5): the features gate recovered sq1 (base 1.0 / gate-none 0.0);
always-hard flipped 3 questions the other way (sq4, tq3, mq3) and added 2
abstentions + 2.6× latency.

**Conclusion (H-GATE, directional at n=20):** the score-feature gate sits at
the best operating point of the three; never-escalating loses recoverable
questions; always-escalating loses different ones and pays 2.6× latency.

### H-GATE full power (M11, merged run `67a1dc06`, 98Q × 4 arms = 392 triples)

The pilot's direction was re-tested at full power on the owner's Windows
workstation under WSL2 (RTX 2070 Super), 5 parallel runners one-per-scenario
on separate `JEVRAG_DATA_DIR`s (§6 of
[docs/dev/project-status-2026-09-30.md](dev/project-status-2026-09-30.md)), then merged by
[`backend/scripts/_merge_par_run.py`](../backend/scripts/_merge_par_run.py).
Full readout: [testbench-results-hgate.md](testbench-results-hgate.md) +
[.json](testbench-results-hgate.json) twin. 1 documented error row kept
visible (musique `mq14/oracle-gate` Dashscope `APITimeoutError`), 391 scored.

| arm | corr | 95% CI | abstain | escalate | p50 ms | cost | Δacc vs base | CI95 | McNemar p | FDR q |
|---|---|---|---|---|---|---|---|---|---|---|
| always-hard | 0.6735 | [0.58, 0.76] | 26 | 1.0 | 73174.5 | 0.1881 | +0.000 | [−0.071, +0.071] | 1.000 | 1.000 |
| **base** | **0.6735** | [0.58, 0.76] | 28 | 0.1939 | 20829.45 | 0.1607 | — | — | — | — |
| gate-none | 0.6276 | [0.53, 0.72] | 27 | 0.0 | 18461.6 | 0.1491 | −0.046 | [−0.112, +0.015] | 0.424 | 0.944 |
| oracle-gate | 0.6392 | [0.54, 0.73] | 25 | 0.3163 | 20830.3 | 0.1508 | −0.036 | [−0.108, +0.036] | 0.629 | 0.944 |

Gate calibration (features gate vs ground-truth answerability, at the run's recorded
θ = 0.6): base acc 0.857 / Brier 0.117 / ECE 0.16 / FN-on-answerable 0.143; gate-none
acc 0.806 / Brier 0.148 / ECE 0.192 / FN-on-answerable 0.194.

**Verdict at full power (objective, negatives kept visible):**

1. **H-GATE is NOT confirmed.** The pilot's "gate > gate-none" direction
   holds in sign (+4.6pp base − gate-none) but is **not significant** at
   n=98 (McNemar p 0.424, FDR q 0.944 after BH across arms). The 20Q pilot's
   "direction" was correctly read as *directional*; full power lacks the
   headroom to call it. The honest headline is: the gate's marginal value
   over never-escalating is small and not statistically established on this
   benchmark mix.
2. **Forced escalation is a pure cost, confirmed at full power.**
   always-hard ties base accuracy (±0.0, p 1.0) at **3.5× median latency**
   and +17% per-question cost. The hard path's per-question benefit is
   eaten by its multi-step token burn when applied unconditionally.
3. **The oracle gate undercuts base** (−3.4pp, n.s.) — inverting the
   pilot's "oracle ≥ base" expectation. **This verdict did not survive
   re-measurement:** the same arm in the full 9-arm suite `36abefc6` came in
   at **+2.5pp**, a sign flip, and the 2026-10-04 re-take `4ec32592` at
   **+1.1pp** — two sign changes across three draws of the same arm. Since no
   draw is significant, the
   defensible statement is only that a perfect escalation decision is worth
   ~0 at n=98 — the MuSiQue rerank-regression interaction (see
   [testbench-results-layer1.md](testbench-results-layer1.md) §"Known
   negatives") remains unproven rather than demonstrated.

The pilot's conclusion is **superseded** by this full-power readout; the
pilot remains visible here as the directional pre-declaration, with this
section's verdict as the full-power correction.

### Full Layer-2 suite — current record (merged run `4ec32592`, 98Q × 9 arms = 882 triples, 2026-10-04)

The complete 9-arm suite re-run after the cross-encoder started scoring full
chunks instead of 400-char prefixes (`rerank_char_limit=0`). Same 5 public
scenarios, same generator/judge pair, 5 parallel workers, **one contiguous
3.31 h window** (00:56→04:15 local, longest worker musique 197 min) — nothing
was interrupted, so unlike the Oct-1 draw no worker needed a resume. 1 error
row of 882 kept visible (triviaqa `tq2`/`gate-jev`, Dashscope `ReadTimeout`);
$2.7905 of Dashscope API. Per-scenario run ids squad `b5f535b4`, hotpotqa
`5741e7b2`, triviaqa `fcf1b64f`, wiki2 `dbdd63fa`, musique `162a6caf`; merged DB
`backend/data_merged_r2/app.db` (a second output dir on purpose — the merge
rebuilds its output and mints a new unified run id every call). Full readout
with caveats and the three-draw reproducibility table:
[testbench-results-layer2-full9-r2.md](testbench-results-layer2-full9-r2.md) +
[.json](testbench-results-layer2-full9-r2.json) twin.

**Read this before using any absolute number below.** The judge prompt changed
in `db571bf`: it gained an exception scoring a proper abstention as correctness
1.0 when the question is *unanswerable*, and the judge over-applies it on this
all-answerable suite — it reads "the retrieved context lacks this" as "this
question is unanswerable". Correctness **on questions the system answered** is
flat across draws (`base` −0.2pp) while correctness **on abstained rows** went
0.0385 → 0.7586 (`base` +72.0pp), and 0 of the 29 `base` abstentions carried an
empty reference. So the pooled figures below are inflated by a harness defect,
and **absolute `correctness`, absolute cost and absolute latency cannot be
differenced against `36abefc6` or `67a1dc06`** — the cost is higher there only
because `db571bf` also started folding System-Two helper calls into per-row
accounting, which is a measurement fix, not a regression. Within-draw paired
Δ vs `base` *is* comparable across draws. Full audit:
[testbench-results-layer2-full9-r2.md](testbench-results-layer2-full9-r2.md)
§"Read this before quoting any number on this page".

| arm | corr | 95% CI | escalate | p50 ms | cost | Δacc vs base | CI95 | McNemar p | FDR q |
|---|---|---|---|---|---|---|---|---|---|
| gate-jev | **0.8737** | [0.79, 0.93] | 0.4388 | 31462.4 | 0.3276 | +0.031 | [−0.041, +0.103] | 0.581 | 1.000 |
| oracle-gate | 0.8551 | [0.77, 0.91] | 0.3163 | 20746.0 | 0.2984 | +0.011 | [−0.061, +0.084] | 1.000 | 1.000 |
| rerank-none | 0.8469 | [0.76, 0.91] | 1.0 | 71396.25 | 0.5641 | +0.003 | [−0.069, +0.071] | 1.000 | 1.000 |
| **base** | **0.8444** | [0.76, 0.90] | 0.1224 | 17672.0 | 0.2162 | — | — | — | — |
| gate-none | 0.8444 | [0.76, 0.90] | 0.0 | 17733.15 | 0.1635 | +0.000 | [−0.071, +0.071] | 1.000 | 1.000 |
| always-hard | 0.8265 | [0.74, 0.89] | 1.0 | 73874.55 | 0.5701 | −0.018 | [−0.082, +0.043] | 1.000 | 1.000 |
| no-bestof | 0.8163 | [0.73, 0.88] | 0.1224 | 18163.15 | 0.2085 | −0.028 | [−0.100, +0.043] | 0.791 | 1.000 |
| rerank-jev | 0.8112 | [0.72, 0.88] | 0.2347 | 18612.3 | 0.2279 | −0.033 | [−0.112, +0.046] | 0.629 | 1.000 |
| no-verify | 0.7918 | [0.70, 0.86] | 0.1224 | 17677.25 | 0.2143 | −0.053 | [−0.127, +0.020] | 0.332 | 1.000 |

**Verdicts (negatives kept visible):**

1. **Nothing is significant — for the third draw running.** Every q = 1.000 and
   every paired CI crosses zero. Largest effect is `gate-jev` at +3.1pp.
   **And the suite now has a measured noise floor of ±5pp**: `no-verify` runs
   citation verification *after* generation with nothing downstream reading it,
   so it is a structural no-op on the answer — its **−5.3pp** is a direct read of
   LLM-sampling plus judge noise, and it is larger than every arm effect except
   `gate-jev`. Nothing below ±5pp on this suite, in any draw, is interpretable.
2. **H-VERIFY is the noise-floor instrument, not just a null.** H-SELECT remains
   a plain null (`no-bestof` −2.8pp, inside the floor). Verification's real
   finding is the floor itself: two structurally identical runs of `base`
   differ by 5.3pp, which retrospectively demotes most single-delta readings in
   this suite from "small effect" to "unmeasurable".
3. **H-RERANK still contradicts the retrieval layer.** `rerank-none` ties `base`
   (+0.3pp) at 4.04× median latency and 2.61× cost with *identical* retrieval
   quality — hit@1 0.9388 both — and it escalates 100% of questions, so it is
   really "RRF-only + always escalate". With the CE now on full chunks `base`
   has the best hit@1 *and* best MRR of any arm and still gains nothing from
   it end-to-end: the CE earns its place in the ranking, not in the answer.
   This does not license removing it (it is the layer the v3 design is built on,
   and it is what makes hit@4 = 1.0).
4. **The gate's marginal value is +0.0pp — and the drift is the finding.** The
   three-draw reproducibility table in
   [testbench-results-layer2-full9-r2.md](testbench-results-layer2-full9-r2.md)
   gives `oracle-gate` −3.6 / +2.5 / +1.1pp on identical arms and knobs: two
   sign changes, never significant. Escalation itself fell (`base` escalates
   12.2% here vs 19.4% on Oct-1), consistent with hit@4 reaching 1.0 and leaving
   the gate less to fix. Do not quote an H-GATE arm delta from one run.
5. **`gate-jev` is still the multi-hop specialist, at the same direction.**
   +7.0pp over `base` on multi-hop (n=57) while losing 2.6pp on single-hop —
   the Oct-1 draw read +10.5 / −4.9pp on the same split. The direction replicates
   at roughly two thirds the magnitude, which puts it inside the ±5pp floor:
   read it as a consistent direction, not an effect size. Its coverage
   calibration is the suite's best ECE (0.2502), its answerability calibration
   the worst (acc 0.66 at its own θ = 0.5).

**Judge-independent evidence — the one thing this draw does confirm.** These
metrics never pass through the LLM judge, so they *are* comparable across
draws, and they confirm the full-chunk cross-encoder fix end-to-end: `base`
hit@1 0.9184 → **0.9388**, MRR 0.9439 → **0.9694**, hit@4 now **1.0000** (all 98
questions have a gold file in the final top-4). That independently reproduces
the Layer-1 offline full-chunk prediction of +2.1/+2.2pp measured on 2026-10-03
([testbench-results-layer1.md](testbench-results-layer1.md) §"Re-run
2026-10-03"). Read `rerank-none`'s +5.1pp hit@1 as the retrieval-layer noise
floor, not a gain: it runs no cross-encoder, so the fix cannot explain it.

**Gate calibration and the loss mode.** On the retrieval-coverage basis
`base` sits at acc 0.7347 / Brier 0.2587 / ECE 0.2628 at the shipped θ = 0.6 —
closer to Layer-1's offline full-chunk calibration (acc 0.7245, Brier 0.269) than
the Oct-1 draw's 0.271, as expected now that both layers feed the CE the same
text. `rerank-jev` is the best-Brier gate (0.233); θ = 0.6 remains the right
operating point. Over-abstention is still the dominant loss mode: `base` declines
29/98 (29.6%) and 26/57 (45.6%) of multi-hop questions, all of them
retrieval-coverage failures rather than gate errors.

### Full Layer-2 suite — prior draw (merged run `36abefc6`, 98Q × 9 arms = 882 triples, 2026-10-01)

The first complete suite, and the draw the 2026-10-04 re-take above supersedes.
Kept as the record of the Oct-1 run and the pre-regression metric baseline —
remember that its absolute `correctness`, cost and latency are **not**
comparable with the re-take (different judge protocol). Its within-draw Δ vs
`base` values remain valid, and finding 3 below is now the middle of a
three-draw reproducibility series.

The four M11 arms above are a subset. This run executed all nine pre-declared
arms on the same 5 parallel-worker path, so H-RERANK, H-SELECT and H-VERIFY are
now measured alongside H-GATE. Full readout with caveats and the
reproducibility table:
[testbench-results-layer2-full9.md](testbench-results-layer2-full9.md) +
[.json](testbench-results-layer2-full9.json) twin; chart
[assets/img/layer2-arm-results.png](assets/img/layer2-arm-results.png)
(rendered from the merged DB, so every number on it is measured).
0 error rows of 882; $1.482 of Dashscope API; ~3.6 h compute, longest worker
212 min. A WSL restart mid-run killed two workers, which were resumed under
their original run ids — no scenario is split across runs.

| arm | corr | 95% CI | escalate | p50 ms | cost | Δacc vs base | CI95 | McNemar p | FDR q |
|---|---|---|---|---|---|---|---|---|---|
| rerank-none | **0.7194** | [0.62, 0.80] | 1.0 | 73600.1 | 0.1854 | **+0.061** | [+0.005, +0.122] | 0.180 | 1.000 |
| gate-jev | 0.699 | [0.60, 0.78] | 0.4286 | 31048.3 | 0.1602 | +0.041 | [−0.025, +0.112] | 0.302 | 1.000 |
| oracle-gate | 0.6837 | [0.59, 0.77] | 0.3163 | 24553.05 | 0.1568 | +0.025 | [−0.041, +0.092] | 0.607 | 1.000 |
| always-hard | 0.6633 | [0.57, 0.75] | 1.0 | 72837.15 | 0.186 | +0.005 | [−0.056, +0.066] | 1.000 | 1.000 |
| no-verify | 0.6633 | [0.57, 0.75] | 0.1939 | 18488.5 | 0.1512 | +0.005 | [−0.031, +0.041] | 1.000 | 1.000 |
| **base** | **0.6582** | [0.56, 0.74] | 0.1939 | 19644.75 | 0.1614 | — | — | — | — |
| no-bestof | 0.6531 | [0.55, 0.74] | 0.1939 | 19127.45 | 0.1465 | −0.005 | [−0.046, +0.031] | 1.000 | 1.000 |
| rerank-jev | 0.6531 | [0.55, 0.74] | 0.2245 | 25132.05 | 0.18 | −0.005 | [−0.097, +0.087] | 1.000 | 1.000 |
| gate-none | 0.6327 | [0.53, 0.72] | 0.0 | 18739.6 | 0.1544 | −0.025 | [−0.082, +0.025] | 0.549 | 1.000 |

**Verdicts (negatives kept visible):**

1. **Nothing is significant.** Every q = 1.000. At n=98 the pre-declared power
   floor is ~10–15pp and the largest effect here is 6.1pp. The suite's honest
   headline is a set of well-measured nulls, not a ranking.
2. **H-SELECT and H-VERIFY are null.** Removing best-of-2 (−0.5pp) or citation
   verification (+0.5pp) changes nothing measurable; `no-bestof` is also the
   cheapest arm. Their justification is the trustworthiness of the `[n]` labels
   in the UI, not judged accuracy.
3. **H-RERANK contradicts Layer 1 end-to-end.** `rerank-none` — no reranker at
   all — is the best arm and the only comparison whose bootstrap CI excludes
   zero, while Layer-1 ranked RRF+cross the best retriever. Mechanism caveat:
   without a cross-encoder score the features gate collapses and that arm
   escalates 100% of questions, so it is really "RRF-only + always-hard", and
   it beat both `base` (+6.1pp) and `always-hard` (+0.5pp). This marks the
   cross-encoder's top-4 selection as suspect; it does not license removing it.
4. **The gate's marginal value is +2.5pp, not +4.6pp** — and the drift itself is
   the finding. See the reproducibility table in
   [testbench-results-layer2-full9.md](testbench-results-layer2-full9.md):
   identical arms and knobs one day apart moved `oracle-gate` by +6.1pp.
5. **`gate-jev` is a multi-hop specialist.** +10.5pp over base on multi-hop
   (the largest single effect in the run) and −4.9pp on single-hop, with the
   worst calibration in the suite (acc 0.633 / ECE 0.448 at its own θ = 0.5).
   The v2 regression and the v3 win condition live in the same arm; the split
   argues for a multi-hop-only gate, which is what v3 approximates with scores.

**Status after the 2026-10-04 re-take:** finding 1 stands across three draws
(all q = 1.000) and the suite now has a measured ±5pp noise floor; finding 2's
H-VERIFY null became the instrument that measured it (`no-verify` at −5.3pp);
finding 3 replicates at a tenth of the effect size (+0.3pp) and its "only CI
excluding zero" caveat no longer applies now that the cross-encoder sees full
chunks; finding 4's drift is now three draws with two sign changes on
`oracle-gate`; finding 5 replicates in direction at two thirds the magnitude.
None of the five was overturned, and none grew into an established effect.

## Cost of the whole M9 session

~$0.45 of Dashscope API (headline $0.31 both arms + judge, testbench $0.10),
~4.7 h of chained sandbox windows, zero lost questions (resumable drivers).

## What this means for jev-like models (interim synthesis)

- Post-answer citation verification + best-of-2 selection (relative judgments):
  retained; the hybrid's single-hop win runs through them.
- Absolute sufficiency gating pre-retrieval: removed in v3, and every
  measurement since agrees (gate accuracy 0.898 vs 0.72, Brier 0.10 vs 0.38,
  single-hop −7.3pp → +9.8pp).
- Pointwise reranking: replaced by the cross-encoder (Layer-1: jev rerank is
  the weakest reranker, −3.5pp vs no rerank).
- The escalating hard path still pays for itself overall (pooled +5.1pp at
  LOWER cost than the baseline), but its value is now concentrated in
  recovery/abstention behavior rather than raw multi-hop accuracy.
