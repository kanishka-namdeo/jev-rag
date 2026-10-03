# Results

> This page summarizes results. For detailed statistical analysis, follow the links to individual run reports.

---

## 🏆 Headline Finding (v3, 2026-09-29)

> Across 5 public benchmarks (98 questions), hybrid RAG with the v3 score-feature escalation gate achieved **66.8% correctness** vs traditional RAG's **61.7%** — a **+5.1pp improvement** (McNemar p = 0.065). On single-hop questions the win is nominally significant: **+9.8pp** (unadjusted Wilcoxon p = 0.048 — a pre-declared subset claim, not FDR-controlled; apply the same "one draw is not a finding" rule used for H-GATE). The hybrid also **costs less** ($0.148 vs $0.165 per suite) and **abstains less** (25.5% vs 35.7% over-abstention).

---

## Key Findings

- **The v2 single-hop regression is fixed and inverted.** The gate inversion (decide sufficiency *after* retrieval, from score features, not by asking a 0.5B model for absolute judgments) turned −7.3pp into **+9.8pp** on single-hop questions (unadjusted p = 0.048; see the FDR caveat in the headline above).

- **The multi-hop edge compressed because the baseline got that good.** The upgraded retrieval stack (BM25 ‖ dense + RRF + cross-encoder) lifted the traditional arm's multi-hop performance, eating most of the v2 multi-hop win. The hybrid's residual multi-hop value is ~nil at n=57.

- **Forced escalation is pure cost.** always-escalating ties base accuracy (+0.5pp, p = 1.0) at **3.71× median latency** and +15% cost — the one Layer-2 result that replicated across both the 4-arm draw `67a1dc06` (3.5×, +17%) and the full 9-arm suite `36abefc6` (882 triples). The score-feature gate sits at the best operating point.

- **Dropping the reranker beat every arm — as a hypothesis, not a ship.** In `36abefc6`, `rerank-none` (RRF only, no cross-encoder) was the best arm at 0.7194 (**+6.1pp** vs base) and the *only* comparison whose bootstrap CI excludes zero ([+0.5, +12.2]), contradicting Layer-1's "cross-encoder is the best retriever." It is p = 0.18, FDR q = 1.000, costs 3.75× latency, and degenerates into always-escalating (its gate feature needs the cross-encoder score), so it marks the cross-encoder's top-4 selection as suspect rather than a new default.

- **A single Layer-2 draw is not a finding.** Every 9-arm comparison has BH-FDR q = 1.000, and re-running the four M11 arms one day later flipped `oracle-gate`'s delta from −3.6pp to **+2.5pp** (sign flip). Quote both draws (`67a1dc06` + `36abefc6`) or neither.

- **The abandoned v2 gate is a multi-hop specialist.** `gate-jev` (absolute sufficiency, θ = 0.5) was second-best overall (**+4.1pp**) and beat base by **+10.5pp on multi-hop** — the largest single effect in `36abefc6` — while losing 4.9pp on single-hop: the v2 failure mode and the v3 win condition in the same arm.

- **The passage battery was the v2 regression.** With one flag flipped (`HYBRID_PASSAGE_BATTERY=false`), the v2 pipeline recovered from −20.8pp to +5.2pp. The battery's absolute thresholds are miscalibrated for the 0.8B stand-in.

- **Cross-encoder rerank dominates Jev rerank.** Layer-1 retrieval: RRF + cross-encoder hits 0.918 hit@1, 0.942 MRR@10. Jev noul rerank is the *weakest* reranker (−3.3pp vs no rerank at all).

---

## Results by Area

### v3 Headline — Traditional vs Hybrid (both upgraded)

Run `16814bd5`, 98 questions, 5 public scenarios, independent judge (kimi-k2.5):

| | Traditional v3 | Hybrid v3 | Δ |
|---|---|---|---|
| **Correctness (pooled)** | 61.7% | **66.8%** | +5.1pp, CI [−0.5, +10.7], p = 0.065 |
| **Single-hop (n=41)** | 80.5% | **90.2%** | **+9.8pp, CI [+2.4, +19.5], p = 0.048 ✓** |
| Multi-hop (n=57) | 48.2% | 50.0% | +1.8pp, n.s. |
| Over-abstention | 35.7% | **25.5%** | −10.2pp |
| Latency p50 | 19.9s | 40.9s | 2.06× |
| Cost per suite | $0.165 | **$0.148** | hybrid cheaper |

→ Full statistics: [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md)

### Retrieval Ablations (Layer-1)

Offline eval, 98 questions, no cloud LLM. RRF + cross-encoder is the best precision retriever (hit@1 0.918, MRR 0.942). BM25 alone is significantly worse on recall (−6.2pp, p = 0.001) but complementary. Jev rerank degrades the fused ranking.

→ Full results: [testbench-results-layer1.md](testbench-results-layer1.md)

### Layer-2 Pipeline Testbench (full 9-arm suite)

Run `36abefc6`, 98Q × 9 arms × 5 public scenarios = 882 triples, 0 error rows, $1.482. **No
arm beats `base` at FDR q < 0.05** — the largest effect in the suite is 6.1 pp against a
pre-declared power floor of ~10–15 pp at n=98. The score-feature gate's marginal value over
never-escalating is **+2.5 pp** (p = 0.549); best-of-2 selection (−0.5 pp) is null and citation
verification (+0.5 pp) is a structural null (post-answer observation arm — see below);
`rerank-none` is the top arm (+6.1 pp, the only CI excluding zero) and `gate-jev` is
second (+4.1 pp) and wins multi-hop by +10.5 pp while losing single-hop by 4.9 pp.
Over-abstention (26.5 % on answerable questions, 43.9 % multi-hop — human-validated as
retrieval-coverage failures) is the largest effect in the data and belongs to no arm.

→ Full results, caveats and the M11 reproducibility table: [testbench-results-layer2-full9.md](testbench-results-layer2-full9.md)

### H-GATE Full Power (prior 4-arm draw)

Run `67a1dc06`, 98Q × 4 arms = 392 triples. The same four arms re-measured a day apart:
gate marginal value +4.6 pp (p = 0.424, q = 0.944) and `oracle-gate` **−3.6 pp** — versus
+2.5 pp and **+2.5 pp** in `36abefc6`. The sign flip is the point: neither draw is
significant, and an H-GATE arm delta from one run of this suite is not a finding. Only
always-escalating-as-pure-cost replicated (3.5× → 3.71× latency).

→ Full results: [testbench-results-hgate.md](testbench-results-hgate.md)

### Public Benchmarks (v2, pre-upgrade)

Five canonical datasets (SQuAD, HotpotQA, TriviaQA, 2WikiMultiHopQA, MuSiQue), 98 questions. Hybrid wins every multi-hop benchmark (+12 to +25pp) and loses on single-hop (SQuAD −12pp, TriviaQA 0pp). Pooled: +7.6pp (multi-hop subset +18.4pp, single-hop −7.3pp).

→ Wave 1 (SQuAD + HotpotQA): [benchmark-public.md](benchmark-public.md)
→ Wave 2 (TriviaQA + 2Wiki + MuSiQue): [benchmark-public-wave2.md](benchmark-public-wave2.md)

### v2 Battery Ablation

Run `bf05f585`, 48 questions, 6 internal scenarios. Battery OFF recovers from −20.8pp to +5.2pp (n.s.). 4/6 scenarios match or exceed v1-level hybrid numbers.

→ Full attribution: [benchmark-v2-ablation.md](benchmark-v2-ablation.md)

### Full Run History

All runs (v1, v2 battery on/off, public waves, v3 headline) with per-scenario breakdowns, loss taxonomy, and confound disclosures.

→ Complete history: [benchmark-results.md](benchmark-results.md)

---

## v1 → v2 → v3 Progression

```
              v1 (4-slot)        v2 (7-slot, battery off)    v3 (escalation gate)
              ─────────────      ────────────────────────    ────────────────────
Internal      +8.3pp             +5.2pp (n.s.)               —
(48Q, 6scen)  p=0.125            p=0.375

Public        —                  +7.6pp                      +5.1pp (p=0.065)
(98Q, 5scen)                     single-hop: −7.3pp          single-hop: +9.8pp ✓
                                 multi-hop: +18.4pp          multi-hop: +1.8pp (n.s.)

Latency       30.5s p50          58.3s p50 (3.5×)            40.9s p50 (2.06×)
Cost          $0.0004/q          $0.0017/q                   $0.0015/q (suite $0.148)

Key lesson    relative signals   absolute gates need         score-feature gate
              work; absolute     per-corpus calibration      fixes single-hop;
              gates don't        before shipping             multi-hop edge
                                                               compressed by
                                                               modern baseline
```

---

## How to Reproduce

All benchmarks run through the built-in **Benchmark Lab** (UI) or the API:

```bash
# Via API (from backend/)
curl -X POST localhost:8000/api/bench/runs \
  -H 'Content-Type: application/json' \
  -d '{"scenario_ids":["techdocs","finance","policy","distractor","multilingual","outofscope"]}'

# Analysis
cd backend && .venv/bin/python scripts/analyze_bench_run.py <run_id>
```

Full methodology: scenario taxonomy, metric definitions, judge fairness protocol, and statistical tests are documented in [benchmarking.md](benchmarking.md). Testbench hypotheses and arms are pre-declared in [testbench-design.md](testbench-design.md). On a workstation, a full suite runs several times faster with one worker per scenario on its own data directory — launch, monitor, resume and merge procedure in [parallel-bench-runbook.md](parallel-bench-runbook.md).

**Reproducibility notes:**
- All five public benchmark scenarios ship in the repo — a fresh clone runs them with zero dataset downloads
- Independent judge (kimi-k2.5), position-swapped pairwise, 9-canary self-test (8 before the 2026-10-03 judge-prompt update)
- Every number carries n, the paired statistic, and the CI
- Negative results reported with the same prominence as positive ones
