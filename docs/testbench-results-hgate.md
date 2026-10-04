# Testbench report — 67a1dc06-a3bd-4bf1-8f25-092cd5db3eff

> **Superseded as the current Layer-2 record**, twice over. The full 9-arm run
> [testbench-results-layer2-full9.md](testbench-results-layer2-full9.md) (`36abefc6`,
> 2026-10-01) re-ran these same four arms one day later and found the `oracle-gate` delta had
> flipped sign; the 2026-10-04 re-take
> [testbench-results-layer2-full9-r2.md](testbench-results-layer2-full9-r2.md) (`4ec32592`)
> re-ran them a third time and `oracle-gate` changed sign again (−0.036 → +0.025 → +0.011).
> Treat the arm deltas below as one sample of a comparison whose noise floor is ~±5 pp, not as
> an established effect. This page stays as the record of the M11 run itself, and as the
> earliest of the three draws in the reproducibility comparison. Note that absolute
> `correctness` is comparable only *within* a draw — the newest draw's judge over-scores
> abstentions (see that page).

label: H-GATE full power (par x5, merged 2026-09-30)

| arm | n | corr | 95% CI | abstain | escalate | p50 ms | cost | Δacc vs base | CI95 | McNemar p | FDR q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| always-hard | 98 | 0.6735 | [0.58, 0.76] | 26 | 1.0 | 73174.5 | 0.1881 | +0.000 | [-0.071, +0.071] | 1.000 | 1.000 |
| base | 98 | 0.6735 | [0.58, 0.76] | 28 | 0.1939 | 20829.45 | 0.1607 | — | — | — | — |
| gate-none | 98 | 0.6276 | [0.53, 0.72] | 27 | 0.0 | 18461.6 | 0.1491 | -0.046 | [-0.112, +0.015] | 0.424 | 0.944 |
| oracle-gate | 98 | 0.6392 | [0.54, 0.73] | 25 | 0.3163 | 20830.3 | 0.1508 | -0.036 | [-0.108, +0.036] | 0.629 | 0.944 |

## gate calibration (sufficiency_p vs ground-truth answerability)

| arm | n | thr | acc | Brier | ECE | FN(ans) | FP(unans) |
|---|---|---|---|---|---|---|---|
| base | 98 | 0.6 | 0.8571 | 0.1169 | 0.16 | 0.1429 | — |
| gate-none | 98 | 0.6 | 0.8061 | 0.1483 | 0.1919 | 0.1939 | — |

*Regenerated 2026-10-01 with the corrected operating point: `analyze_testbench.py` used to
read `gate_score_threshold` from the top level of `bench_runs.config` while
`run_testbench.py` records it under `config["base"]`, so this table was computed at a
phantom 0.5. The run used 0.6 (`backend/.env`), which is what is shown now. The arm table
above is unaffected.*

## subset: single_hop

| arm | n | corr | abstain | p50 ms |
|---|---|---|---|---|
| always-hard | 41 | 0.8537 | 3 | 76375.0 |
| base | 41 | 0.8902 | 2 | 19943.7 |
| gate-none | 41 | 0.8293 | 4 | 18837.4 |
| oracle-gate | 41 | 0.7927 | 5 | 17727.7 |

## subset: multi_hop

| arm | n | corr | abstain | p50 ms |
|---|---|---|---|---|
| always-hard | 57 | 0.5439 | 23 | 71372.3 |
| base | 57 | 0.5175 | 26 | 22117.2 |
| gate-none | 57 | 0.4825 | 23 | 18334.6 |
| oracle-gate | 57 | 0.5268 | 20 | 52497.35 |
