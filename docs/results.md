# Results

> This page summarizes results. For detailed statistical analysis, follow the links to individual run reports.

---

## 🏆 Headline Finding (v3, 2026-09-29)

> Across 5 public benchmarks (98 questions), hybrid RAG with the v3 score-feature escalation gate achieved **66.8% correctness** vs traditional RAG's **61.7%** — a **+5.1pp improvement** (McNemar p = 0.065). On single-hop questions the win is **significant**: **+9.8pp** (Wilcoxon p = 0.048). The hybrid also **costs less** ($0.148 vs $0.165 per suite) and **abstains less** (25.5% vs 35.7% over-abstention).

---

## Key Findings

- **The v2 single-hop regression is fixed and inverted.** The gate inversion (decide sufficiency *after* retrieval, from calibrated scores, not by asking a 0.5B model for absolute judgments) turned −7.3pp into **+9.8pp significant** on single-hop questions.

- **The multi-hop edge compressed because the baseline got that good.** The upgraded retrieval stack (BM25 ‖ dense + RRF + cross-encoder) lifted the traditional arm's multi-hop performance, eating most of the v2 multi-hop win. The hybrid's residual multi-hop value is ~nil at n=57.

- **Forced escalation is pure cost.** The H-GATE full-power testbench (392 triples) confirmed: always-escalating ties base accuracy (±0.0, p = 1.0) at **3.5× median latency** and +17% cost. The score-feature gate sits at the best operating point.

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

### H-GATE Full Power (Layer-2 Testbench)

Run `67a1dc06`, 98Q × 4 arms = 392 triples. The score-feature gate's marginal value over never-escalating is +4.6pp but **not significant** (McNemar p = 0.424, FDR q = 0.944). Always-escalating is confirmed pure cost. The oracle gate undercuts base (−3.4pp).

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

Full methodology: scenario taxonomy, metric definitions, judge fairness protocol, and statistical tests are documented in [benchmarking.md](benchmarking.md). Testbench hypotheses and arms are pre-declared in [testbench-design.md](testbench-design.md).

**Reproducibility notes:**
- All five public benchmark scenarios ship in the repo — a fresh clone runs them with zero dataset downloads
- Independent judge (kimi-k2.5), position-swapped pairwise, 8/8 canary self-test
- Every number carries n, the paired statistic, and the CI
- Negative results reported with the same prominence as positive ones
