#!/usr/bin/env python3
"""Statistical power analysis for benchmark comparisons.

Computes minimum detectable effect (MDE) and required sample size for paired
benchmark comparisons using statsmodels. This addresses the critical issue that
most RAG benchmarks are underpowered for detecting small but meaningful differences.

Usage:
    python scripts/power_analysis.py --run-id <run_id>
    python scripts/power_analysis.py --p1 0.875 --p2 0.927 --n 48 --rho 0.5

References:
    - clawRxiv 2604.01974: Power Analysis for Pairwise Model Comparisons
    - statsmodels documentation: https://www.statsmodels.org/stable/stats.html#power
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from statsmodels.stats.power import TTestIndPower, NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize


def compute_mde_paired(
    n: int,
    rho: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Compute minimum detectable effect for paired binary outcomes.

    Args:
        n: Number of questions (paired samples)
        rho: Correlation between the two systems' outcomes (0.0 to 1.0)
        alpha: Significance level (default 0.05)
        power: Statistical power (default 0.80)

    Returns:
        Minimum detectable effect size (Cohen's d)

    Interpretation:
        - Small effect: d ≈ 0.2
        - Medium effect: d ≈ 0.5
        - Large effect: d ≈ 0.8

    For paired tests, the effective sample size is n * (1 - rho), so higher
    correlation increases power (reduces MDE).
    """
    # For paired test, adjust for correlation
    # Effective sample size: n_eff = n * (1 - rho)
    # But we use the paired t-test formula directly
    analysis = TTestIndPower()

    # Solve for effect size given n, alpha, power
    # For paired test, ratio=1.0 (equal groups)
    effect_size = analysis.solve_power(
        nobs1=n,
        alpha=alpha,
        power=power,
        ratio=1.0,
        alternative="two-sided",
    )

    # Adjust for pairing: paired test has variance (1-rho) * var_independent
    # So MDE_paired = MDE_independent * sqrt(1-rho)
    mde_paired = effect_size * np.sqrt(1 - rho)

    return float(mde_paired)


def compute_required_n(
    effect_size: float,
    rho: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """Compute required sample size to detect a given effect size.

    Args:
        effect_size: Cohen's d effect size to detect
        rho: Correlation between the two systems' outcomes
        alpha: Significance level (default 0.05)
        power: Statistical power (default 0.80)

    Returns:
        Required number of questions (rounded up)
    """
    analysis = TTestIndPower()

    # Solve for n given effect_size, alpha, power
    n_independent = analysis.solve_power(
        effect_size=effect_size,
        alpha=alpha,
        power=power,
        ratio=1.0,
        alternative="two-sided",
    )

    # Adjust for pairing: paired test needs n * (1-rho) samples
    n_paired = n_independent / (1 - rho)

    return int(np.ceil(n_paired))


def compute_mde_proportions(
    n: int,
    p1: float,
    p2: float,
    rho: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Compute MDE for paired proportion comparison (McNemar-style).

    This is more appropriate for binary accuracy metrics than Cohen's d.

    Args:
        n: Number of questions
        p1: Expected accuracy of system 1 (0.0 to 1.0)
        p2: Expected accuracy of system 2 (0.0 to 1.0)
        rho: Correlation between outcomes
        alpha: Significance level
        power: Statistical power

    Returns:
        Minimum detectable difference in proportions (percentage points)
    """
    # Use normal approximation for paired proportions
    analysis = NormalIndPower()

    # Effect size for proportions (Cohen's h)
    h = proportion_effectsize(p2, p1)

    # Solve for n
    n_independent = analysis.solve_power(
        effect_size=h,
        alpha=alpha,
        power=power,
        ratio=1.0,
        alternative="two-sided",
    )

    # Adjust for pairing
    n_paired = n_independent / (1 - rho)

    # Convert back to proportion difference
    # This is approximate; for exact McNemar, need discordant pairs
    # But this gives a reasonable estimate
    mde_proportion = abs(p2 - p1) * (n / n_paired)

    return float(mde_proportion)


def estimate_correlation(trad_correct: list[bool], hyb_correct: list[bool]) -> float:
    """Estimate correlation between two systems' outcomes from benchmark data.

    Args:
        trad_correct: List of booleans (True=correct, False=incorrect) for traditional
        hyb_correct: List of booleans for hybrid

    Returns:
        Pearson correlation coefficient (0.0 to 1.0)
    """
    if len(trad_correct) != len(hyb_correct):
        raise ValueError("Lists must have same length")
    if len(trad_correct) < 2:
        return 0.5  # default assumption

    # Convert to numeric
    x = np.array(trad_correct, dtype=float)
    y = np.array(hyb_correct, dtype=float)

    # Compute Pearson correlation
    corr = np.corrcoef(x, y)[0, 1]

    # Clamp to [0, 1] (negative correlation is unusual for similar systems)
    return float(np.clip(corr, 0.0, 1.0))


def analyze_run(run_id: str) -> dict:
    """Analyze a specific benchmark run and compute power metrics.

    Args:
        run_id: The benchmark run ID to analyze

    Returns:
        Dictionary with power analysis results
    """
    from app.db import BenchResult, db_session
    from sqlalchemy import select

    with db_session() as session:
        results = session.execute(
            select(BenchResult).where(BenchResult.run_id == run_id)
        ).scalars().all()

    if not results:
        raise ValueError(f"No results found for run {run_id}")

    # Group by question and extract correctness
    questions = {}
    for r in results:
        qid = r.question_id
        if qid not in questions:
            questions[qid] = {"traditional": None, "hybrid": None}

        mode = r.mode
        if r.generation and r.generation.get("correctness") is not None:
            # Binarize: correctness >= 0.5 is correct
            correct = r.generation["correctness"] >= 0.5
            questions[qid][mode] = correct

    # Extract paired outcomes
    trad_correct = []
    hyb_correct = []
    for qid, outcomes in questions.items():
        if outcomes["traditional"] is not None and outcomes["hybrid"] is not None:
            trad_correct.append(outcomes["traditional"])
            hyb_correct.append(outcomes["hybrid"])

    n = len(trad_correct)
    if n == 0:
        raise ValueError("No paired outcomes found")

    # Compute accuracies
    p1 = sum(trad_correct) / n
    p2 = sum(hyb_correct) / n

    # Estimate correlation
    rho = estimate_correlation(trad_correct, hyb_correct)

    # Compute MDE (Cohen's d)
    mde_d = compute_mde_paired(n, rho)

    # Compute MDE for proportions
    mde_prop = compute_mde_proportions(n, p1, p2, rho)

    # Compute required n for observed effect
    observed_diff = abs(p2 - p1)
    if observed_diff > 0:
        # Convert proportion difference to Cohen's d (approximate)
        # For binary outcomes, d ≈ 2 * arcsin(sqrt(p)) difference
        h = proportion_effectsize(p2, p1)
        required_n = compute_required_n(h, rho)
    else:
        required_n = None

    # Interpret results
    interpretation = []
    if mde_d >= 0.8:
        interpretation.append(f"⚠️  Underpowered: MDE={mde_d:.2f} (large effect). Need n≥{required_n or '?'} to detect smaller effects.")
    elif mde_d >= 0.5:
        interpretation.append(f"⚠️  Moderate power: MDE={mde_d:.2f} (medium effect). Can detect medium-large effects.")
    else:
        interpretation.append(f"✅ Well-powered: MDE={mde_d:.2f} (small-medium effect). Can detect meaningful differences.")

    if required_n and n < required_n:
        interpretation.append(f"📊 Current n={n} is below required n={required_n} for the observed effect ({observed_diff:.1%}).")

    return {
        "run_id": run_id,
        "n_questions": n,
        "traditional_accuracy": round(p1, 4),
        "hybrid_accuracy": round(p2, 4),
        "observed_difference": round(observed_diff, 4),
        "estimated_correlation_rho": round(rho, 4),
        "minimum_detectable_effect": {
            "cohens_d": round(mde_d, 4),
            "proportion_difference": round(mde_prop, 4),
            "interpretation": "small" if mde_d < 0.5 else "medium" if mde_d < 0.8 else "large",
        },
        "required_sample_size": {
            "for_observed_effect": required_n,
            "for_small_effect_d0.2": compute_required_n(0.2, rho),
            "for_medium_effect_d0.5": compute_required_n(0.5, rho),
            "for_large_effect_d0.8": compute_required_n(0.8, rho),
        },
        "power_analysis": {
            "alpha": 0.05,
            "power": 0.80,
            "test": "paired t-test (two-sided)",
        },
        "interpretation": interpretation,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Statistical power analysis for benchmark comparisons"
    )
    parser.add_argument(
        "--run-id",
        type=str,
        help="Benchmark run ID to analyze",
    )
    parser.add_argument(
        "--p1",
        type=float,
        help="Accuracy of system 1 (for manual calculation)",
    )
    parser.add_argument(
        "--p2",
        type=float,
        help="Accuracy of system 2 (for manual calculation)",
    )
    parser.add_argument(
        "--n",
        type=int,
        help="Number of questions (for manual calculation)",
    )
    parser.add_argument(
        "--rho",
        type=float,
        default=0.5,
        help="Correlation between systems (default: 0.5)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output JSON file (default: stdout)",
    )

    args = parser.parse_args()

    if args.run_id:
        # Analyze existing run
        result = analyze_run(args.run_id)
    elif args.p1 is not None and args.p2 is not None and args.n is not None:
        # Manual calculation
        mde_d = compute_mde_paired(args.n, args.rho)
        mde_prop = compute_mde_proportions(args.n, args.p1, args.p2, args.rho)

        observed_diff = abs(args.p2 - args.p1)
        if observed_diff > 0:
            h = proportion_effectsize(args.p2, args.p1)
            required_n = compute_required_n(h, args.rho)
        else:
            required_n = None

        result = {
            "mode": "manual_calculation",
            "inputs": {
                "p1": args.p1,
                "p2": args.p2,
                "n": args.n,
                "rho": args.rho,
            },
            "minimum_detectable_effect": {
                "cohens_d": round(mde_d, 4),
                "proportion_difference": round(mde_prop, 4),
            },
            "required_sample_size": {
                "for_observed_effect": required_n,
                "for_small_effect_d0.2": compute_required_n(0.2, args.rho),
                "for_medium_effect_d0.5": compute_required_n(0.5, args.rho),
                "for_large_effect_d0.8": compute_required_n(0.8, args.rho),
            },
        }
    else:
        parser.error("Either --run-id or (--p1, --p2, --n) must be provided")
        return

    # Output
    output_json = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Power analysis written to {args.output}")
    else:
        print(output_json)

    # Print interpretation
    print("\n" + "=" * 80)
    print("INTERPRETATION")
    print("=" * 80)
    if "interpretation" in result and isinstance(result["interpretation"], list):
        for line in result["interpretation"]:
            print(line)
    else:
        mde = result["minimum_detectable_effect"]["cohens_d"]
        print(f"Minimum detectable effect: Cohen's d = {mde:.2f}")
        if mde >= 0.8:
            print("⚠️  This benchmark can only detect LARGE effects (d ≥ 0.8).")
            print("   Most RAG pipeline improvements are small-medium (d = 0.2-0.5).")
            print("   Consider increasing n or accepting that small effects are undetectable.")
        elif mde >= 0.5:
            print("⚠️  This benchmark can detect MEDIUM-LARGE effects (d ≥ 0.5).")
            print("   Small effects (d < 0.5) may be missed.")
        else:
            print("✅ This benchmark can detect SMALL-MEDIUM effects (d < 0.5).")
            print("   Well-powered for typical RAG improvements.")


if __name__ == "__main__":
    main()
