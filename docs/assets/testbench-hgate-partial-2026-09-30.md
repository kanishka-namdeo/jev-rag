# Testbench report — be7b62ea-2eb7-467c-aa38-dc8fbf81eb8f

label: H-GATE full power (post-reset fresh)

| arm | n | corr | 95% CI | abstain | escalate | p50 ms | cost | Δacc vs base | CI95 | McNemar p | FDR q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| always-hard | 48 | 0.8333 | [0.70, 0.91] | 6 | 1.0 | 101510.6 | 0.082 | -0.031 | [-0.125, +0.062] | 0.688 | 1.000 |
| base | 48 | 0.8646 | [0.74, 0.93] | 7 | 0.1458 | 36044.65 | 0.0661 | — | — | — | — |
| gate-none | 48 | 0.8021 | [0.67, 0.89] | 5 | 0.0 | 36407.0 | 0.0689 | -0.062 | [-0.167, +0.021] | 0.375 | 1.000 |
| oracle-gate | 48 | 0.8646 | [0.74, 0.93] | 4 | 0.1458 | 38887.15 | 0.0665 | +0.000 | [-0.062, +0.062] | 1.000 | 1.000 |

## gate calibration (sufficiency_p vs ground-truth answerability)

| arm | n | thr | acc | Brier | ECE | FN(ans) | FP(unans) |
|---|---|---|---|---|---|---|---|
| base | 48 | 0.5 | 0.875 | 0.1228 | 0.1572 | 0.125 | — |
| gate-none | 48 | 0.5 | 0.875 | 0.1234 | 0.1589 | 0.125 | — |

## subset: single_hop

| arm | n | corr | abstain | p50 ms |
|---|---|---|---|---|
| always-hard | 25 | 0.88 | 2 | 101519.0 |
| base | 25 | 0.9 | 2 | 36304.9 |
| gate-none | 25 | 0.86 | 2 | 36420.6 |
| oracle-gate | 25 | 0.9 | 1 | 39427.4 |

## subset: multi_hop

| arm | n | corr | abstain | p50 ms |
|---|---|---|---|---|
| always-hard | 23 | 0.7826 | 4 | 98871.3 |
| base | 23 | 0.8261 | 5 | 35784.4 |
| gate-none | 23 | 0.7391 | 3 | 35670.3 |
| oracle-gate | 23 | 0.8261 | 3 | 36839.5 |
