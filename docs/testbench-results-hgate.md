# Testbench report — 67a1dc06-a3bd-4bf1-8f25-092cd5db3eff

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
| base | 98 | 0.5 | 0.8571 | 0.1169 | 0.16 | 0.1429 | — |
| gate-none | 98 | 0.5 | 0.8367 | 0.1483 | 0.1919 | 0.1633 | — |

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
