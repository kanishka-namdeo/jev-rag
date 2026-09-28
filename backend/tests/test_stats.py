"""Paired-stats module tests — hermetic (pure stdlib math, no models/network).

Covers the pre-declared testbench statistics (docs/rag-upgrade-2026.md §4):
exact McNemar, Wilson CI, paired bootstrap, Wilcoxon + rank-biserial,
BH-FDR, Brier, ECE, ROC/threshold sweep. Reference values are verified by
hand (math.comb / explicit formula computations inline).

Run: cd backend && .venv/bin/python -m pytest tests/test_stats.py -q
"""
from __future__ import annotations

import math
import os
import statistics
import tempfile

# Make tests hermetic BEFORE importing app code (same pattern as test_bench.py).
_TMP = tempfile.mkdtemp(prefix="jevrag-stats-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")

import pytest  # noqa: E402

from app.bench.stats import (  # noqa: E402
    best_threshold,
    bh_fdr,
    brier_score,
    ece,
    mcnemar_exact,
    paired_bootstrap_ci,
    roc_sweep,
    summarize_paired_pvals,
    wilcoxon_signed_rank,
    wilson_ci,
)


# ================================================================ mcnemar
def test_mcnemar_exact_classic():
    # b=8, c=1 -> n=9, observed min side k=1. Two-sided exact p =
    # sum of P(X=k) for all k with P(X=k) <= P(X=1); here k in {0,1,8,9},
    # so p = 2 * P(X<=1) = 2 * (1+9)/512 = 20/512.
    n = 9
    p_obs = math.comb(n, 1) / 2**n
    expected = sum(math.comb(n, k) / 2**n for k in range(n + 1)
                   if math.comb(n, k) / 2**n <= p_obs)
    assert expected == pytest.approx(20 / 512)   # hand check of the reference
    assert mcnemar_exact(8, 1) == pytest.approx(0.0391, abs=1e-4)
    assert mcnemar_exact(8, 1) == pytest.approx(expected)


def test_mcnemar_exact_edges():
    assert mcnemar_exact(0, 0) == 1.0            # no discordant pairs
    assert mcnemar_exact(7, 7) == 1.0            # b == c -> observed side is the mode
    assert mcnemar_exact(5, 5) == 1.0
    # fully one-sided: b=0, c=5 -> only k=0 and k=5 are as rare as observed
    assert mcnemar_exact(0, 5) == pytest.approx(2 / 32)
    # symmetric in its arguments
    assert mcnemar_exact(8, 1) == mcnemar_exact(1, 8)
    with pytest.raises(ValueError):
        mcnemar_exact(-1, 3)


# ================================================================ wilson
def test_wilson_ci_contains_point_estimate():
    lo, hi = wilson_ci(8, 10)
    # hand-computed Wilson score interval at 95%
    z = 1.959963985
    p, n = 0.8, 10
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    assert lo == pytest.approx(center - half)
    assert hi == pytest.approx(center + half)
    assert lo < 0.55 < hi
    assert 0.0 <= lo <= hi <= 1.0


def test_wilson_ci_degenerate():
    assert wilson_ci(0, 0) == (0.0, 1.0)
    lo, hi = wilson_ci(0, 5)   # p = 0: classic Wilson [0, 0.434]
    assert lo == 0.0 and 0.0 < hi < 0.5
    lo, hi = wilson_ci(5, 5)
    assert hi == 1.0 and 0.5 < lo < 1.0


# ================================================================ bootstrap
def test_bootstrap_constant_diffs():
    diffs = [1.0] * 50
    res = paired_bootstrap_ci(diffs, n_resamples=2000, seed=42)
    assert res["point"] == pytest.approx(1.0)
    assert res["lo"] == pytest.approx(1.0)
    assert res["hi"] == pytest.approx(1.0)


def test_bootstrap_empty():
    assert paired_bootstrap_ci([]) == {"point": 0.0, "lo": 0.0, "hi": 0.0}


def test_bootstrap_seed_determinism():
    diffs = [0.4, -0.2, 0.7, 1.1, -0.5, 0.3, 0.9, -1.3, 0.2, 0.6]
    r1 = paired_bootstrap_ci(diffs, n_resamples=1500, seed=42)
    r2 = paired_bootstrap_ci(diffs, n_resamples=1500, seed=42)
    assert r1 == r2
    r3 = paired_bootstrap_ci(diffs, n_resamples=1500, seed=43)
    assert r3 != r1  # different seed -> different resample stream (verified deterministic)


def test_bootstrap_symmetry():
    # negating every difference negates the bootstrap distribution exactly
    # (same seed -> same resample indices), so the CI must flip sign.
    diffs = [3.0, -1.0, 2.5, -0.5, 4.0, -2.0, 1.5, 0.5]
    r_pos = paired_bootstrap_ci(diffs, n_resamples=1500, seed=123)
    r_neg = paired_bootstrap_ci([-d for d in diffs], n_resamples=1500, seed=123)
    assert r_neg["point"] == pytest.approx(-r_pos["point"])
    assert r_neg["lo"] == pytest.approx(-r_pos["hi"])
    assert r_neg["hi"] == pytest.approx(-r_pos["lo"])
    # data symmetric around zero -> CI roughly symmetric around the 0 point
    sym = [float(i) for i in range(-6, 7)]
    r = paired_bootstrap_ci(sym, n_resamples=5000, seed=7)
    assert r["point"] == pytest.approx(0.0)
    assert r["lo"] < 0.0 < r["hi"]
    assert abs(r["lo"] + r["hi"]) < 0.1


def test_bootstrap_stat_variants():
    diffs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    r = paired_bootstrap_ci(diffs, stat="median", n_resamples=500, seed=9)
    assert r["point"] == pytest.approx(5.5)
    r2 = paired_bootstrap_ci(diffs, stat=statistics.median, n_resamples=500, seed=9)
    assert r2["point"] == pytest.approx(5.5)
    r3 = paired_bootstrap_ci(diffs, stat=max, n_resamples=500, seed=9)
    assert r3["point"] == pytest.approx(10.0)
    with pytest.raises(ValueError):
        paired_bootstrap_ci(diffs, stat="trimmed")
    with pytest.raises(ValueError):
        paired_bootstrap_ci(diffs, confidence=1.5)


# ================================================================ wilcoxon
def test_wilcoxon_all_positive():
    res = wilcoxon_signed_rank([1, 2, 3, 4, 5, 6, 7, 8])
    assert res["n"] == 8
    assert res["w"] == 0.0                       # W- = 0 -> min(W+, W-) = 0
    # documented formulation: z = (W+ - mean +/- 0.5)/sd, W+ = 36, no ties
    n = 8
    mean_w = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24
    z = (36 - mean_w - 0.5) / math.sqrt(var)
    expected_p = math.erfc(abs(z) / math.sqrt(2))
    assert res["p"] == pytest.approx(expected_p)
    assert res["p"] < 0.05                       # ~0.0143 with continuity correction
    assert res["rank_biserial"] == 1.0           # all ranks favorable


def test_wilcoxon_symmetric_mixed():
    diffs = [1, -1, 2, -2, 3, -3, 4, -4]
    res = wilcoxon_signed_rank(diffs)
    assert res["n"] == 8
    # average ranks for ties: +/-k share rank 2k-0.5 -> W+ = W- = 18
    assert res["w"] == pytest.approx(18.0)
    assert res["rank_biserial"] == pytest.approx(0.0)
    assert res["p"] > 0.2                        # perfectly balanced -> large p


def test_wilcoxon_drops_zeros():
    with_zeros = [0.0, 1, 2, 3, 4, 5, 6, 7, 8]
    without = [1, 2, 3, 4, 5, 6, 7, 8]
    r1 = wilcoxon_signed_rank(with_zeros)
    r2 = wilcoxon_signed_rank(without)
    assert r1["n"] == 8                          # the zero pair is dropped
    assert r1["p"] == pytest.approx(r2["p"])
    assert r1["w"] == pytest.approx(r2["w"])
    assert r1["rank_biserial"] == pytest.approx(r2["rank_biserial"])
    # all-zero input: nothing to test
    r0 = wilcoxon_signed_rank([0.0, 0.0, 0.0])
    assert r0 == {"n": 0, "w": 0.0, "p": 1.0, "rank_biserial": 0.0}


def test_wilcoxon_too_small_n():
    res = wilcoxon_signed_rank([1, 2, 3, 4])     # n = 4 < 5
    assert res["n"] == 4
    assert res["p"] == 1.0                       # documented guard
    assert res["rank_biserial"] == 1.0           # effect size still reported


# ================================================================ bh_fdr
def test_bh_fdr_textbook():
    pvals = [0.01, 0.04, 0.03, 0.005]
    adjusted = bh_fdr(pvals)
    assert adjusted == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert len(adjusted) == len(pvals)           # input order preserved


def test_bh_fdr_monotone():
    pvals = [0.9, 0.03, 0.001, 0.5, 0.42, 0.005, 0.2, 0.35]
    adjusted = bh_fdr(pvals)
    pairs = sorted(zip(pvals, adjusted), key=lambda t: t[0])
    qs = [q for _, q in pairs]
    assert all(qs[i] <= qs[i + 1] + 1e-12 for i in range(len(qs) - 1))
    assert all(0.0 <= q <= 1.0 for q in adjusted)


def test_bh_fdr_clamps_and_edges():
    assert bh_fdr([1.5, 0.02]) == pytest.approx([1.0, 0.04])   # p > 1 clamped
    # p < 0 clamped to 0; step-up keeps monotonicity: q(0.04) stays 0.04
    assert bh_fdr([-0.1, 0.04]) == pytest.approx([0.0, 0.04])
    assert bh_fdr([]) == []
    assert bh_fdr([0.3]) == pytest.approx([0.3])               # m = 1


# ================================================================ brier
def test_brier_perfect_and_worst():
    assert brier_score([1.0, 0.0], [1, 0]) == pytest.approx(0.0)
    assert brier_score([0.0, 1.0], [1, 0]) == pytest.approx(1.0)
    assert brier_score([0.8, 0.4], [1, 0]) == pytest.approx(0.1)  # (0.04+0.16)/2


def test_brier_input_validation():
    with pytest.raises(ValueError):
        brier_score([0.5, 0.6], [1, 0, 1])
    with pytest.raises(ValueError):
        brier_score([], [])


# ================================================================ ece
def test_ece_perfectly_calibrated():
    # 10 predictions at 0.8, 8 of them correct: bin confidence 0.8 == bin
    # accuracy 0.8 -> ECE 0. ("8 ones + 2 zeros" at a matching score.)
    scores = [0.8] * 10
    outcomes = [1] * 8 + [0] * 2
    assert ece(scores, outcomes) == pytest.approx(0.0)
    # multi-bin calibrated: 4/5 correct at 0.8 and 2/5 correct at 0.4
    scores2 = [0.8] * 5 + [0.4] * 5
    outcomes2 = [1, 1, 1, 1, 0, 1, 1, 0, 0, 0]
    assert ece(scores2, outcomes2) == pytest.approx(0.0)


def test_ece_miscalibrated():
    # the anti-example: confident-and-wrong in both populated bins
    scores = [0.8] * 8 + [0.2] * 2
    outcomes = [1] * 8 + [0] * 2
    # bin [0.8,0.9): 8 items, |1.0 - 0.8| * 0.8 = 0.16
    # bin [0.2,0.3): 2 items, |0.0 - 0.2| * 0.2 = 0.04  -> ECE = 0.2
    assert ece(scores, outcomes) == pytest.approx(0.2)
    assert ece(scores, outcomes) > 0.0
    # maximally miscalibrated: always says 1.0, always wrong
    assert ece([1.0, 1.0, 1.0, 1.0], [0, 0, 0, 0]) == pytest.approx(1.0)


def test_ece_input_validation():
    with pytest.raises(ValueError):
        ece([0.5, 0.6], [1, 0, 1])
    with pytest.raises(ValueError):
        ece([], [])


# ================================================================ roc sweep
def test_roc_sweep_hand_case():
    scores = [0.9, 0.8, 0.7, 0.3]
    labels = [1, 0, 1, 0]      # P = 2, N = 2
    rows = roc_sweep(scores, labels)
    assert [r["threshold"] for r in rows] == [0.9, 0.8, 0.7, 0.3, float("-inf")]
    by_t = {r["threshold"]: r for r in rows}

    r = by_t[0.9]              # only 0.9 predicted positive
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 0, 1, 2)
    assert r["tpr"] == pytest.approx(0.5) and r["fpr"] == pytest.approx(0.0)
    assert r["youden_j"] == pytest.approx(0.5)

    r = by_t[0.8]              # 0.9 and 0.8 positive
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (1, 1, 1, 1)
    assert r["youden_j"] == pytest.approx(0.0)

    r = by_t[0.7]              # 0.9, 0.8, 0.7 positive
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2, 1, 0, 1)
    assert r["tpr"] == pytest.approx(1.0) and r["fpr"] == pytest.approx(0.5)

    r = by_t[0.3]              # everything positive
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2, 2, 0, 0)
    assert r["tpr"] == pytest.approx(1.0) and r["fpr"] == pytest.approx(1.0)

    r = by_t[float("-inf")]    # sentinel: all predicted positive
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2, 2, 0, 0)
    assert r["tpr"] == pytest.approx(1.0) and r["fpr"] == pytest.approx(1.0)
    assert r["youden_j"] == pytest.approx(0.0)


def test_roc_sweep_unique_thresholds_only():
    rows = roc_sweep([0.5, 0.5, 0.3], [1, 0, 0])
    assert [r["threshold"] for r in rows] == [0.5, 0.3, float("-inf")]
    assert (rows[0]["tp"], rows[0]["fp"], rows[0]["fn"], rows[0]["tn"]) == (1, 1, 0, 1)
    with pytest.raises(ValueError):
        roc_sweep([0.5], [1, 0])


def test_best_threshold():
    # perfectly separable: 0.8 admits both positives and no negative
    best = best_threshold([0.9, 0.8, 0.7, 0.3], [1, 1, 0, 0])
    assert best is not None
    assert best["threshold"] == pytest.approx(0.8)
    assert best["youden_j"] == pytest.approx(1.0)

    # non-separable: J = 0.5 at t=0.9 and t=0.7 -> tie broken to higher t
    best = best_threshold([0.9, 0.8, 0.7, 0.3], [1, 0, 1, 0])
    assert best is not None
    assert best["threshold"] == pytest.approx(0.9)
    assert best["youden_j"] == pytest.approx(0.5)

    assert best_threshold([0.1, 0.2], [0, 0]) is None   # no positives
    assert best_threshold([0.1, 0.2], [1, 1]) is None   # no negatives
    assert best_threshold([], []) is None


# ================================================================ summary
def test_summarize_paired_pvals():
    pvals = {"H-GATE": 0.01, "H-RERANK": 0.04, "H-SELECT": 0.03, "H-VERIFY": 0.005}
    out = summarize_paired_pvals(pvals)
    assert out["raw"] == pvals
    assert out["adjusted"] == pytest.approx(
        {"H-GATE": 0.02, "H-RERANK": 0.04, "H-SELECT": 0.04, "H-VERIFY": 0.02})
    assert out["n_significant_005"] == 4


def test_summarize_paired_pvals_mixed_significance():
    pvals = {"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5}
    out = summarize_paired_pvals(pvals)
    # BH: sorted p = .01,.03,.04,.5 -> q = .04,.0533,.0533,.5 (monotone step-up)
    assert out["adjusted"]["a"] == pytest.approx(0.04)
    assert out["adjusted"]["b"] == pytest.approx(0.04 * 4 / 3)
    assert out["adjusted"]["c"] == pytest.approx(0.04 * 4 / 3)
    assert out["adjusted"]["d"] == pytest.approx(0.5)
    # significance count matches adjusted q < 0.05 by construction
    manual = sum(1 for q in out["adjusted"].values() if q < 0.05)
    assert manual == 1
    assert out["n_significant_005"] == manual
    # neutral on empty grid
    assert summarize_paired_pvals({}) == {
        "raw": {}, "adjusted": {}, "n_significant_005": 0}
