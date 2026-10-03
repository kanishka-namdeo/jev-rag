"""Paired-statistics testbench for the two-arm RAG benchmarks (pure stdlib).

Implements the PRE-DECLARED analysis plan from docs/rag-upgrade-2026.md §4
("Statistics (pre-declared)"): exact McNemar on discordant pairs, paired
bootstrap 95% CI (percentile method — 50,000 resamples in production use; the
default here is 10,000 so unit tests stay fast, production callers pass
n_resamples=50_000), Wilcoxon signed-rank + rank-biserial for graded paired
scores, and Benjamini-Hochberg FDR across the hypothesis grid
(H-GATE / H-RERANK / H-SELECT / H-VERIFY / H-HARDPATH).

This is the stdlib-only successor of the app-side summary statistics in
scripts/analyze_bench_run.py (which needs numpy/scipy/statsmodels and runs
only after a completed run): the same families of tests, but deterministic
given a seed and importable from the backend app itself. Only `math`,
`random` and `statistics` are used — no numpy, no scipy.

Conventions:
- every function is pure (no I/O, no global state); the bootstrap is
  deterministic given `seed` (a fresh random.Random(seed) per call);
- p-values are two-sided unless stated otherwise;
- degenerate inputs return documented neutral values (never NaN) so JSON
  summaries stay machine-parseable;
- gate/calibration helpers (Brier, ECE, ROC sweep, best threshold) support
  the Layer-1 gate-calibration plan: "Threshold θ is calibrated on labeled
  eval data, not hand-tuned" (docs/rag-upgrade-2026.md §3.3).
"""
from __future__ import annotations

import math
import random
import statistics

__all__ = [
    "mcnemar_exact",
    "wilson_ci",
    "paired_bootstrap_ci",
    "wilcoxon_signed_rank",
    "bh_fdr",
    "brier_score",
    "first_gate_score",
    "ece",
    "roc_sweep",
    "best_threshold",
    "summarize_paired_pvals",
]


# ---------------------------------------------------------------------------
# 1. Exact McNemar (paired binary outcomes)
# ---------------------------------------------------------------------------

def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs of a 2x2 table.

    b = #pairs where arm A succeeded and arm B failed, c = the reverse
    (which arm is which does not matter — the test is symmetric).
    Under H0 (both arms equal), X = min-side count ~ Binomial(n=b+c, 0.5).

    Two-sided p = sum of P(X=k) over all k with P(X=k) <= P(X=k_obs),
    where k_obs = min(b, c) — the "smaller tail plus everything rarer"
    convention, identical to scipy.stats.binomtest(min(b, c), b+c, 0.5)
    for these inputs. Capped at 1.0.

    Edge cases: b = c = 0 (no discordant pairs) -> 1.0 (no evidence against
    H0). b == c (any split) -> 1.0 (observed side is the mode).

    Exact test is pre-declared for the testbench; for very large discordant
    counts callers may switch to the chi-square variant, but the repo's
    paired runs have n_discordant << 100, where exact is cheap.
    """
    if b < 0 or c < 0:
        raise ValueError(f"discordant counts must be non-negative, got b={b}, c={c}")
    n = b + c
    if n == 0:
        return 1.0
    k_obs = min(b, c)
    p_obs = math.comb(n, k_obs) / (2.0 ** n)
    total = 0.0
    for k in range(n + 1):
        pk = math.comb(n, k) / (2.0 ** n)
        if pk <= p_obs:
            total += pk
    return min(total, 1.0)


# ---------------------------------------------------------------------------
# 2. Wilson score interval (binomial proportion)
# ---------------------------------------------------------------------------

def wilson_ci(k: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n.

    z defaults to the two-sided 95% normal quantile (Phi^-1(0.975)
    = 1.959963985). Interval is clamped to [0, 1].

    n = 0 -> (0.0, 1.0): the uninformative interval (differs deliberately
    from scripts/analyze_bench_run.py, which returns NaN there — the
    testbench wants JSON-safe neutral values).

    Requires 0 <= k <= n (the formula is only meaningful for a proportion;
    out-of-range input raises via the sqrt domain check or is meaningless).
    """
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


# ---------------------------------------------------------------------------
# 3. Paired bootstrap CI (percentile method)
# ---------------------------------------------------------------------------

def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation percentile on a pre-sorted list; q in [0, 100].

    Matches numpy.percentile(..., method="linear") so results are
    cross-checkable against the scipy-based analysis script.
    """
    n = len(sorted_vals)
    if n == 0:
        raise ValueError("percentile of empty list")
    if n == 1:
        return float(sorted_vals[0])
    pos = (n - 1) * (q / 100.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_vals[int(pos)])
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def paired_bootstrap_ci(
    diffs: list[float],
    stat: str | callable = "mean",
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> dict:
    """Percentile bootstrap CI for a statistic of paired differences.

    diffs: per-question (arm B - arm A) differences; resampled with
    replacement (random.Random(seed) — a fresh generator per call, so the
    result is deterministic given the seed).

    stat: "mean" (default; statistics.fmean) | "median" (statistics.median)
    | any callable taking a list of floats and returning a float.

    Returns {"point": stat(original diffs), "lo": ..., "hi": ...} with
    lo/hi the alpha/2 and 1-alpha/2 percentiles (linear interpolation) of
    the bootstrap distribution of stat — the plain percentile method.

    Production use: 50,000 resamples per the pre-declared plan
    (docs/rag-upgrade-2026.md §4); the default 10,000 keeps unit tests fast.

    Empty diffs -> {"point": 0.0, "lo": 0.0, "hi": 0.0} (no pairs, no
    effect — JSON-safe neutral value).
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be >= 1, got {n_resamples}")
    if callable(stat):
        apply_stat = stat
    elif stat == "mean":
        apply_stat = statistics.fmean
    elif stat == "median":
        apply_stat = statistics.median
    else:
        raise ValueError(f"unknown stat {stat!r} (use 'mean', 'median' or a callable)")

    if not diffs:
        return {"point": 0.0, "lo": 0.0, "hi": 0.0}

    point = float(apply_stat(list(diffs)))
    rng = random.Random(seed)
    n = len(diffs)
    boot: list[float] = []
    for _ in range(n_resamples):
        sample = rng.choices(diffs, k=n)
        boot.append(float(apply_stat(sample)))
    boot.sort()
    alpha = 1.0 - confidence
    lo = _percentile(boot, 100.0 * (alpha / 2.0))
    hi = _percentile(boot, 100.0 * (1.0 - alpha / 2.0))
    return {"point": point, "lo": lo, "hi": hi}


# ---------------------------------------------------------------------------
# 4. Wilcoxon signed-rank + rank-biserial
# ---------------------------------------------------------------------------

def wilcoxon_signed_rank(diffs: list[float]) -> dict:
    """Two-sided Wilcoxon signed-rank test on paired differences.

    Formulation (documented, scipy-compatible convention):

    1. Zero differences are dropped (zero_method="wilcox"); n counts the
       non-zero pairs only.
    2. |diff| values are ranked 1..n, average ranks for ties.
    3. W+ = sum of ranks of positive diffs, W- = sum of ranks of negative
       diffs. The returned "w" is the classic statistic W = min(W+, W-).
    4. Normal approximation with continuity correction and tie-corrected
       variance (the z-statistic uses W+, whose null mean is n(n+1)/4):

           mean = n(n+1)/4
           var  = (n(n+1)(2n+1) - sum_over_tie_groups(t^3 - t)) / 24
           z    = (W+ - mean - 0.5)/sd   if W+ > mean
                  (W+ - mean + 0.5)/sd   if W+ < mean
                  0.0                     if W+ == mean

       (the 0.5 pulls the statistic toward its null mean — standard
       continuity correction; scipy.stats.wilcoxon(correction=True) uses
       the same rule. Using W+ rather than the returned min-side W avoids
       an extra sign flip.)
    5. p = erfc(|z|/sqrt(2)) — the two-sided normal survival function,
       computed exactly in float via math.erfc.
    6. n < 5 -> p = 1.0 (normal approximation is meaningless that small;
       the pre-declared plan works at n ~ 98 pooled, so this guard only
       fires on tiny subsets — documented, not hidden).
    7. rank_biserial = (W+ - W-) / (W+ + W-)  — Kerby's favorable /
       unfavorable rank difference, equivalent to 2*W+/(n(n+1)/2) - 1.
       Range [-1, 1]; 0 = no directional effect.

    Returns {"n": int, "w": float, "p": float, "rank_biserial": float}.
    All-zero (or empty) input -> n = 0, w = 0.0, p = 1.0,
    rank_biserial = 0.0 (no non-zero pairs to test).
    """
    nz = [float(d) for d in diffs if d != 0.0]
    n = len(nz)
    if n == 0:
        return {"n": 0, "w": 0.0, "p": 1.0, "rank_biserial": 0.0}

    # ranks of |diff| with average ranks for ties
    absvals = [abs(d) for d in nz]
    order = sorted(range(n), key=lambda i: absvals[i])
    ranks = [0.0] * n
    tie_corr = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and absvals[order[j + 1]] == absvals[order[i]]:
            j += 1
        # sorted positions i..j (0-based) hold 1-based ranks i+1..j+1
        avg_rank = (i + 1 + j + 1) / 2.0
        for pos in range(i, j + 1):
            ranks[order[pos]] = avg_rank
        t = j - i + 1
        tie_corr += t ** 3 - t
        i = j + 1

    w_plus = sum(r for r, d in zip(ranks, nz) if d > 0.0)
    w_minus = sum(r for r, d in zip(ranks, nz) if d < 0.0)
    w = min(w_plus, w_minus)
    total_rank = w_plus + w_minus  # = n(n+1)/2
    rank_biserial = (w_plus - w_minus) / total_rank if total_rank > 0 else 0.0

    if n < 5:
        p = 1.0
    else:
        mean_w = n * (n + 1) / 4.0
        var = (n * (n + 1) * (2 * n + 1) - tie_corr) / 24.0
        sd = math.sqrt(var)
        delta = w_plus - mean_w
        if delta > 0:
            z = (delta - 0.5) / sd
        elif delta < 0:
            z = (delta + 0.5) / sd
        else:
            z = 0.0
        p = math.erfc(abs(z) / math.sqrt(2.0))

    return {"n": n, "w": float(w), "p": float(p),
            "rank_biserial": float(rank_biserial)}


# ---------------------------------------------------------------------------
# 5. Benjamini-Hochberg FDR
# ---------------------------------------------------------------------------

def bh_fdr(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg step-up adjusted q-values (FDR control).

    q_(k) = min over j >= k of min(m/j * p_(j), 1), computed right-to-left
    so the result is monotone non-decreasing in the sorted p-values; input
    order is preserved (one adjusted value per input). p-values outside
    [0, 1] are clamped into range before adjustment.

    Empty input -> []. Example (classic textbook): [0.01, 0.04, 0.03, 0.005]
    -> [0.02, 0.04, 0.04, 0.02].
    """
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 1.0
    for k in range(m, 0, -1):  # rank k (1-based), largest p first
        i = order[k - 1]
        p = min(max(float(pvalues[i]), 0.0), 1.0)
        running = min(running, p * m / k)
        adjusted[i] = running
    return adjusted


# ---------------------------------------------------------------------------
# 6. Calibration metrics (gate / judge scores vs binary outcomes)
# ---------------------------------------------------------------------------

def first_gate_score(decisions: list[dict] | None, fallback: float | None = None,
                     jev_threshold: float = 0.5) -> float | None:
    """The gate reading that actually drove the easy/hard decision.

    The done event's `sufficiency_p` is the LAST gate reading — on the hard path
    it is re-evaluated after decompose/re-retrieve, so scoring the gate on it
    mixes two measurement points. The FIRST `gate` decision record is the one
    that chose the path:
    - features/none mode: `probabilities.top1` (the score vs the threshold);
    - jev mode: the raw sufficiency probability in `answer` (escalation means it
      fell BELOW the threshold, but the score itself is still p);
    - injected (bench never/always/oracle override): no score was read —
      falls back (these arms don't test the gate, they bound it).
    `fallback` (usually the done-event sufficiency_p) covers rows whose
    decisions predate the record shape. None when neither exists.
    """
    for d in decisions or []:
        if not isinstance(d, dict) or d.get("name") != "gate":
            continue
        if d.get("mode") == "jev":
            ans = d.get("answer")
            if isinstance(ans, bool):
                return fallback
            return float(ans) if isinstance(ans, (int, float)) else fallback
        top1 = (d.get("probabilities") or {}).get("top1")
        if isinstance(top1, bool):
            return fallback
        return float(top1) if isinstance(top1, (int, float)) else fallback
    return fallback


def brier_score(scores: list[float], outcomes: list[int]) -> float:
    """Mean squared error of probabilistic scores against 0/1 outcomes.

    brier = mean((score - outcome)^2); 0 = perfect, 1 = perfectly wrong
    (for 0/1 scores). Length mismatch or empty input -> ValueError
    (a mean over zero pairs is undefined — and silently returning 0.0
    would read as "perfectly calibrated" in a report).
    """
    if len(scores) != len(outcomes):
        raise ValueError(
            f"length mismatch: {len(scores)} scores vs {len(outcomes)} outcomes")
    if not scores:
        raise ValueError("empty inputs: Brier score is undefined for zero pairs")
    return statistics.fmean([(s - o) ** 2 for s, o in zip(scores, outcomes)])


def ece(scores: list[float], outcomes: list[int], n_bins: int = 10) -> float:
    """Expected calibration error, equal-width bins over [0, 1].

    ece = sum over non-empty bins of (n_bin / n) * |acc_bin - conf_bin|,
    where acc_bin = mean(outcomes) and conf_bin = mean(scores) within the
    bin. Empty bins are skipped. Scores are expected in [0, 1]; scores
    that fall outside are assigned to the nearest edge bin (clamped index)
    rather than raising, so a stray 1.0000001 does not kill a report.

    Length mismatch -> ValueError. Empty input -> ValueError (same
    reasoning as brier_score: 0.0 would masquerade as perfect calibration).
    """
    if len(scores) != len(outcomes):
        raise ValueError(
            f"length mismatch: {len(scores)} scores vs {len(outcomes)} outcomes")
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}")
    n = len(scores)
    if n == 0:
        raise ValueError("empty inputs: ECE is undefined for zero pairs")

    bin_n = [0] * n_bins
    bin_conf = [0.0] * n_bins
    bin_acc = [0] * n_bins
    for s, o in zip(scores, outcomes):
        idx = int(s * n_bins)
        if idx < 0:
            idx = 0
        elif idx >= n_bins:
            idx = n_bins - 1
        bin_n[idx] += 1
        bin_conf[idx] += s
        bin_acc[idx] += o

    total = 0.0
    for b in range(n_bins):
        if bin_n[b] == 0:
            continue
        conf = bin_conf[b] / bin_n[b]
        acc = bin_acc[b] / bin_n[b]
        total += (bin_n[b] / n) * abs(acc - conf)
    return total


# ---------------------------------------------------------------------------
# 7. ROC / threshold sweep (gate calibration on retrieval-score features)
# ---------------------------------------------------------------------------

def roc_sweep(scores: list[float], labels: list[int]) -> list[dict]:
    """Confusion counts at every unique threshold, sorted by threshold desc.

    Thresholds are the unique score values; "positive" is predicted when
    score >= threshold. One row per threshold, plus a FINAL sentinel row
    with threshold = -inf (everything predicted positive: tp = P, fp = N,
    fn = 0, tn = 0, tpr = 1, fpr = 1 when both classes are present).

    Row keys: {"threshold", "tp", "fp", "fn", "tn", "tpr", "fpr",
    "youden_j"} with youden_j = tpr - fpr. Counts are ints; tpr/fpr are
    0.0 when the corresponding true class is absent (degenerate-input
    convention; best_threshold returns None in that case anyway).

    Length mismatch -> ValueError.
    """
    if len(scores) != len(labels):
        raise ValueError(
            f"length mismatch: {len(scores)} scores vs {len(labels)} labels")
    n_pos = sum(1 for y in labels if y)
    n_neg = len(labels) - n_pos

    def _row(t: float, tp: int, fp: int, fn: int, tn: int) -> dict:
        tpr = tp / n_pos if n_pos > 0 else 0.0
        fpr = fp / n_neg if n_neg > 0 else 0.0
        return {"threshold": t, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "tpr": tpr, "fpr": fpr, "youden_j": tpr - fpr}

    rows: list[dict] = []
    for t in sorted(set(scores), reverse=True):
        tp = fp = 0
        for s, y in zip(scores, labels):
            if s >= t:
                if y:
                    tp += 1
                else:
                    fp += 1
        rows.append(_row(t, tp, fp, n_pos - tp, n_neg - fp))
    # sentinel: predict positive for everything (threshold -inf)
    rows.append(_row(float("-inf"), n_pos, n_neg, 0, 0))
    return rows


def best_threshold(scores: list[float], labels: list[int]) -> dict | None:
    """Argmax Youden's J row from roc_sweep (ties -> higher threshold first).

    Ties are broken toward the higher threshold because rows are visited
    in threshold-descending order and only strict improvements replace the
    current best. Returns None when the labels contain no positives or no
    negatives (a threshold is meaningless without both classes).
    """
    if len(scores) != len(labels):
        raise ValueError(
            f"length mismatch: {len(scores)} scores vs {len(labels)} labels")
    if not any(y for y in labels) or not any(not y for y in labels):
        return None
    best: dict | None = None
    for row in roc_sweep(scores, labels):
        if best is None or row["youden_j"] > best["youden_j"]:
            best = row
    return best


# ---------------------------------------------------------------------------
# 8. Hypothesis-grid summary
# ---------------------------------------------------------------------------

def summarize_paired_pvals(pvals: dict[str, float]) -> dict:
    """BH-FDR summary across the named hypotheses of the testbench grid.

    Input: {hypothesis_name: raw p-value}. Output:
    {"raw": {...},                    # the input p-values (float)
     "adjusted": {...},               # BH-FDR q-values, same keys
     "n_significant_005": int}        # count of adjusted q < 0.05

    This is the pre-declared multiple-comparison control across the
    hypothesis grid (docs/rag-upgrade-2026.md §4); key order follows the
    input dict. Empty input -> empty dicts and count 0.
    """
    names = list(pvals.keys())
    raw = {name: float(pvals[name]) for name in names}
    adjusted_list = bh_fdr([pvals[name] for name in names])
    adjusted = dict(zip(names, adjusted_list))
    n_sig = sum(1 for q in adjusted_list if q < 0.05)
    return {"raw": raw, "adjusted": adjusted, "n_significant_005": n_sig}
