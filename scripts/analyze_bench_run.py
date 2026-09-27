"""Statistical analysis for a completed bench run (objective reporting).

Applies the tests from research task 8-r (grounded in Dietterich 1998, Demšar 2006,
statsforevals.com guidance):

1. McNemar's test (exact binomial when discordant pairs < 25) on paired
   binary correctness (correct = generation.correctness >= 0.5 threshold,
   reported at two thresholds; primary = >= 0.5).
2. Wilcoxon signed-rank (two-sided, zero_method='wilcox') on paired continuous
   correctness scores.
3. Paired bootstrap percentile CI (10k resamples, seed fixed) for the mean
   difference of every reported aggregate metric.
4. Pairwise win/tie/loss with exact binomial tie-inclusive win-rate CI
   (Wilson interval), and position-consistency disclosure.
5. Verbosity-bias probe: Spearman corr(answer length, judge correctness) per arm
   (LLM-judge style/verbosity bias check, statsforevals "trusting judges").

Reads run results straight from the SQLite DB (no API dependency). Prints a
compact JSON blob to stdout for pasting into docs.

Usage:
  python analyze_bench_run.py RUN_ID [--db sqlite:///.../custom.db]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict

import numpy as np
from scipy import stats as sps
from statsmodels.stats.contingency_tables import mcnemar

sys.path.insert(0, "/home/z/my-project/backend")
from app.db import BenchResult, BenchRun, db_session  # noqa: E402
from sqlalchemy import select  # noqa: E402

CORRECT_THRESHOLD = 0.5


def wilson_ci(k: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def paired_bootstrap_ci(diffs: np.ndarray, n_boot: int = 10_000, seed: int = 7):
    if diffs.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, diffs.size, size=(n_boot, diffs.size))
    means = diffs[idx].mean(axis=1)
    point = float(diffs.mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return (round(point, 4), round(float(lo), 4), round(float(hi), 4))


def mcnemar_analysis(trad_bin, hyb_bin) -> dict:
    """trad_bin/hyb_bin: boolean arrays, paired per question."""
    n01 = int(np.sum(trad_bin & ~hyb_bin))  # traditional correct, hybrid wrong
    n10 = int(np.sum(~trad_bin & hyb_bin))  # hybrid correct, traditional wrong
    b, c = n01, n10
    if b + c == 0:
        return {"n01_trad_only": b, "n10_hybrid_only": c, "p_value": None,
                "note": "no discordant pairs — identical binary outcomes"}
    exact = (b + c) < 25
    if exact:
        # exact binomial two-sided
        res = sps.binomtest(min(b, c), b + c, 0.5)
        p = float(res.pvalue)
        method = "exact binomial"
    else:
        tbl = [[0, b], [c, 0]]
        p = float(mcnemar(tbl, exact=False).pvalue)
        method = "chi2 continuity-corrected"
    return {"n01_trad_only": b, "n10_hybrid_only": c, "method": method,
            "p_value": round(p, 5), "significant_at_0.05": p < 0.05}


def wilcoxon_analysis(trad, hyb) -> dict:
    diffs = hyb - trad
    nz = int(np.sum(diffs != 0))
    if nz == 0:
        return {"n_pairs": int(diffs.size), "nonzero_diffs": 0,
                "p_value": None, "note": "all differences zero"}
    try:
        res = sps.wilcoxon(hyb, trad, zero_method="wilcox", mode="auto")
        p = float(res.pvalue)
    except ValueError as e:
        return {"n_pairs": int(diffs.size), "error": str(e)}
    # rank-biserial effect size
    absd = np.abs(diffs[diffs != 0])
    ranks = sps.rankdata(absd)
    r_plus = float(np.sum(ranks[diffs[diffs != 0] > 0]))
    r_minus = float(np.sum(ranks[diffs[diffs != 0] < 0]))
    n = len(absd)
    rbc = (r_plus - r_minus) / (n * (n + 1) / 2)
    return {"n_pairs": int(diffs.size), "nonzero_diffs": nz,
            "p_value": round(p, 5), "significant_at_0.05": p < 0.05,
            "rank_biserial": round(rbc, 4),
            "median_diff": round(float(np.median(diffs)), 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--db", default="sqlite:///./db/custom.db")
    args = ap.parse_args()

    with db_session() as session:
        run = session.get(BenchRun, args.run_id)
        if run is None:
            sys.exit(f"run {args.run_id} not found")
        rows = session.execute(
            select(BenchResult).where(BenchResult.run_id == args.run_id)
        ).scalars().all()

    # pair rows by (scenario, question)
    by_q: dict[tuple, dict[str, BenchResult]] = defaultdict(dict)
    errors = 0
    for r in rows:
        by_q[(r.scenario_id, r.question_id)][r.mode] = r
        if r.error:
            errors += 1

    pairs = [v for v in by_q.values() if "traditional" in v and "hybrid" in v
             and not v["traditional"].error and not v["hybrid"].error]
    n_expected = run.progress_total or len(by_q)
    print(f"# run {run.id} label={run.label!r}", file=sys.stderr)
    print(f"# pairs analysed: {len(pairs)}/{n_expected} questions "
          f"({errors} error rows excluded)", file=sys.stderr)

    trad_corr = np.array([p["traditional"].generation["correctness"] for p in pairs
                          if p["traditional"].generation
                          and p["traditional"].generation.get("correctness") is not None])
    hyb_corr = np.array([p["hybrid"].generation["correctness"] for p in pairs
                         if p["hybrid"].generation
                         and p["hybrid"].generation.get("correctness") is not None])
    n = min(len(trad_corr), len(hyb_corr))
    trad_corr, hyb_corr = trad_corr[:n], hyb_corr[:n]

    out: dict = {
        "run_id": run.id,
        "label": run.label,
        "pipeline": (run.config or {}).get("pipeline"),
        "n_pairs": int(n),
        "judge_model": run.judge_model,
        "judge_selftest_agreement": (run.judge_selftest or {}).get("agreement"),
    }

    # 1. binary correctness at two thresholds
    for thr in (0.5, 0.75):
        tb = trad_corr >= thr
        hb = hyb_corr >= thr
        out[f"binary_correct@{thr}"] = {
            "traditional_rate": round(float(tb.mean()), 4),
            "hybrid_rate": round(float(hb.mean()), 4),
            "delta_pp": round(float((hb.mean() - tb.mean()) * 100), 2),
            **mcnemar_analysis(tb, hb),
        }

    # 2. continuous correctness
    out["wilcoxon_correctness"] = wilcoxon_analysis(trad_corr, hyb_corr)
    out["mean_correctness"] = {
        "traditional": round(float(trad_corr.mean()), 4),
        "hybrid": round(float(hyb_corr.mean()), 4),
        "bootstrap_ci_of_diff": paired_bootstrap_ci(hyb_corr - trad_corr),
    }

    # 3. faithfulness (secondary metric)
    trad_fa = np.array([p["traditional"].generation["faithfulness"] for p in pairs
                        if p["traditional"].generation
                        and p["traditional"].generation.get("faithfulness") is not None])
    hyb_fa = np.array([p["hybrid"].generation["faithfulness"] for p in pairs
                       if p["hybrid"].generation
                       and p["hybrid"].generation.get("faithfulness") is not None])
    m = min(len(trad_fa), len(hyb_fa))
    if m:
        out["faithfulness"] = {
            "traditional": round(float(trad_fa[:m].mean()), 4),
            "hybrid": round(float(hyb_fa[:m].mean()), 4),
            "wilcoxon": wilcoxon_analysis(trad_fa[:m], hyb_fa[:m]),
            "bootstrap_ci_of_diff": paired_bootstrap_ci(hyb_fa[:m] - trad_fa[:m]),
        }

    # 4. pairwise
    pw = [p["hybrid"].pairwise for p in pairs if p["hybrid"].pairwise]
    if pw:
        wins = sum(1 for p in pw if p.get("winner") == "hybrid")
        losses = sum(1 for p in pw if p.get("winner") == "traditional")
        ties = sum(1 for p in pw if p.get("winner") == "tie")
        n_pw = len(pw)
        wr = (wins + 0.5 * ties) / n_pw
        lo, hi = wilson_ci(wins + ties, n_pw)  # not-tie win CI
        out["pairwise"] = {
            "n": n_pw, "hybrid_wins": wins, "traditional_wins": losses, "ties": ties,
            "win_rate_incl_ties": round(wr, 4),
            "win_rate_ci95_non_tie": [round(lo, 4), round(hi, 4)],
            "position_consistency": round(
                sum(1 for p in pw if p.get("position_consistent")) / n_pw, 4),
        }

    # 5. verbosity-bias probe per arm
    def _len_corr(answers, scores):
        if len(answers) != len(scores) or not len(answers):
            return None
        L = np.array([len(a) for a in answers], dtype=float)
        if np.std(L) == 0 or np.std(scores) == 0:
            return None
        r = sps.spearmanr(L, scores)
        return round(float(r.statistic), 3)

    out["verbosity_probe_spearman_len_vs_correctness"] = {
        "traditional": _len_corr([p["traditional"].answer for p in pairs], trad_corr),
        "hybrid": _len_corr([p["hybrid"].answer for p in pairs], hyb_corr),
    }

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
