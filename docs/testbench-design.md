# Hypothesis-Based Testbench: Design of Record

> Companion to docs/rag-upgrade-2026.md §4. Pre-declared hypotheses, arms,
> metrics and statistics — fixed BEFORE the runs, so results cannot be
> cherry-picked after the fact.

## Why this testbench exists

The research question this repo exists to answer — *where does a small
("jev-like") local model help vs hurt in a RAG pipeline?* — is only answerable
by isolating one placement at a time on paired questions. The literature calls
exactly for this (component-wise pre-registered evaluation; paired bootstrap +
exact McNemar + BH-FDR over declared comparisons — see docs/rag-upgrade-2026.md
§2 refs). Our own history is the cautionary tale: the v2 sufficiency gate's
single-hop failure was confirmed four independent times before anyone could
say "the gate is the problem"; a component-isolating harness would have found
it in one afternoon.

## Two layers, cheap first

### Layer 1 — retrieval testbench (offline, no cloud LLM)

`backend/scripts/eval_retrieval.py` — pure retrieval quality on the 5 public
scenarios (98 questions), CPU-only, minutes:

| Arm | Retrieval | Rerank | Isolates |
|---|---|---|---|
| dense | dense top-10 | none | pre-v3 baseline |
| bm25 | BM25 top-10 | none | lexical alone |
| rrf | BM25‖dense RRF top-10 | none | fusion contribution |
| rrf-cross | RRF top-10 | cross-encoder | the v3 default |
| rrf-jev | RRF top-10 | jev noul | H-RERANK (jev vs cross) |
| dense-cross | dense top-10 | cross-encoder | fusion value ON TOP of rerank |
| bge-cross | dense (bge-small-en-v1.5) top-10 | cross | H-EMBED (swap A/B) |

Metrics: recall@4, hit@1, MRR@10, nDCG@10 (file-level gold, same functions as
the main bench). Paired stats per arm-vs-rrf-cross: exact McNemar on
gold-in-top-4, paired bootstrap 95% CI on recall@4.

**Doubles as gate calibration**: per question, the top-1 cross-encoder score
after RRF+rerank with the label "gold in top-4" feeds `best_threshold`
(Youden J) → the recommended `gate_score_threshold`, reported with accuracy,
Brier and ECE at that operating point.

### Layer 2 — pipeline testbench (cloud LLM, resumable, reaper-proof)

`backend/scripts/run_testbench.py` — one-factor-at-a-time ablations from the
v3 base config, each arm driving the SAME ChatService orchestrator (arm parity
is structural since M5). Pre-declared arms:

| Arm | Override | Hypothesis |
|---|---|---|
| base | v3 defaults (features gate, cross rerank) | reference |
| gate-jev | gate_mode=jev | H-GATE: jev absolute gate vs score features |
| gate-none | gate_mode=none (never escalate) | H-GATE bounder: never-retry |
| always-hard | escalate=True | H-GATE bounder: always-retry |
| oracle-gate | escalate=(gold not in own RRF+cross top-4) | H-GATE ceiling: perfect retry decision |
| rerank-jev | rerank_mode=jev | H-RERANK: jev vs cross end-to-end |
| rerank-none | rerank_mode=none | H-RERANK: no rerank end-to-end |
| no-bestof | hybrid_best_of_n=False | H-SELECT: best-of-2 contribution |
| no-verify | hybrid_verify_answers=False | H-VERIFY: verification cost/latency/trust (NOT accuracy — see below) |

Metrics per arm: judge correctness (kimi-k2.5 absolute), abstention rate,
p50/p95 latency, cost; **paired vs base**: exact McNemar on per-question
correctness, paired bootstrap 95% CI on accuracy delta, BH-FDR across the arm
family (H1..H5 adjusted). H-HARDPATH = base-vs-gate-none (the agentic layer's
total contribution) and always-hard-vs-base (cost of over-escalation).

`backend/scripts/analyze_testbench.py` produces the final table; every number
carries n, the statistic, and the CI.

H-VERIFY is a structural null on accuracy by construction: citation verification runs
*after* generation and nothing downstream reads its output (no regeneration, no
re-ranking), so `no-verify` is generation-identical to `base` — pinned hermetically in
`backend/tests/test_pipeline_v3.py::test_no_verify_arm_is_generation_identical_to_base`.
Any non-zero accuracy delta on this arm is sampling noise. Read it as a
cost/latency/trust characterization (what verification costs, what makes the `[n]`
labels checkable), and scope any future accuracy claim about verification to a
verify→regenerate policy, which would be a different, testable hypothesis.

## Statistical protocol (pre-declared)

- Exact McNemar (two-sided binomial on discordant pairs) for binary outcomes.
- Paired bootstrap, 50,000 resamples, percentile 95% CI, seed fixed (42).
- Wilcoxon signed-rank + rank-biserial for graded scores (faithfulness).
- BH-FDR across the arm family per family definition above.
- Power reality at n≈98 pooled (fewer per-scenario): only effects ≥~10-15pp
  with ≥25% discordance reach p<0.05 — we report pooled + single-hop /
  multi-hop subsets (pre-declared split, as the repo already practices) and
  mark underpowered comparisons as such instead of hiding them.

## Objectivity contract

Arms are fixed before running. Thresholds are calibrated on Layer-1 data only
(never on Layer-2 outcomes). Negative and null results are reported with the
same prominence as wins. If an arm loses, that is a finding about jev-like
model placement, which is the point of the project.

## Operational notes (sandbox constraints)

- Layer 2 runs inside chained tool-call windows via the resumable driver
  (per-question atomic commits, completed (scenario, question, arm) triples
  are skipped on resume — same reaper-proof pattern as bench_resume.py).
- All arms share ONE CrossEncoderReranker session and ONE jev-score subprocess
  (RAM budget); per-arm ChatService instances only override Settings.
- Runs are recorded in the same bench_runs/bench_results tables with
  mode = arm name and config.testbench = true — the standard results tooling
  keeps working.
