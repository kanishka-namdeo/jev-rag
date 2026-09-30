#!/usr/bin/env python3
"""Analyze a Layer-2 testbench run: per-arm metrics + PAIRED stats vs the base
arm (docs/testbench-design.md §statistical protocol).

  .venv/bin/python scripts/analyze_testbench.py RUN_ID [--base base] [--out report.md]

Per arm: n, judge correctness, abstention rate, latency p50/p95, cost,
escalation rate (from gate decisions), gate accuracy/Brier where applicable.
Paired vs base: exact McNemar (b=arm-better, c=base-better), paired bootstrap
95% CI on the accuracy delta (50k resamples, seed 42), BH-FDR adjusted
q-values across the arm family. Also single-hop / multi-hop subset splits.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.bench.metrics import pct  # noqa: E402
from app.bench.stats import (  # noqa: E402
    bh_fdr, brier_score, ece, mcnemar_exact, paired_bootstrap_ci, wilson_ci,
)
from app.db import BenchResult, BenchRun, db_session  # noqa: E402

SINGLE_HOP = {"squad", "triviaqa", "techdocs", "finance", "policy"}
MULTI_HOP = {"hotpotqa", "wiki2", "musique", "distractor"}


def load_rows(run_id: str) -> tuple[dict | None, list[BenchResult]]:
    with db_session() as session:
        run = session.get(BenchRun, run_id)
        rows = session.execute(
            select(BenchResult).where(BenchResult.run_id == run_id)
            .order_by(BenchResult.scenario_id, BenchResult.question_id, BenchResult.mode)
        ).scalars().all()
    return run, rows


def _arm_stats(rows: list[BenchResult], gate_threshold: float = 0.5) -> dict:
    corr = [r.generation["correctness"] for r in rows
            if r.generation and r.generation.get("correctness") is not None]
    abst = defaultdict(int)
    for r in rows:
        if r.generation:
            abst[r.generation.get("abstention", "error")] += 1
    lat = [r.timings.get("latency_ms", 0.0) for r in rows if r.timings]
    esc = [(r.jev_decisions or []) for r in rows]
    n_escalated = sum(1 for decs in esc if any(d.get("name") == "gate" and d.get("answer") == "escalate"
                                               for d in decs))
    gate_rows = [(r.sufficiency_p, r.answerable) for r in rows if r.sufficiency_p is not None]
    out = {
        "n": len(rows),
        "errors": sum(1 for r in rows if r.error),
        "correctness": round(mean(corr), 4) if corr else None,
        "correctness_ci95_wilson": (round(wilson_ci(sum(corr), len(corr))[0], 4),
                                    round(wilson_ci(sum(corr), len(corr))[1], 4)) if corr else None,
        "abstention": dict(abst),
        "escalation_rate": round(n_escalated / len(rows), 4) if rows else None,
        "latency_ms": {"p50": pct(lat, 50), "p95": pct(lat, 95)},
        "cost_usd": round(sum(r.cost_usd or 0 for r in rows), 4),
        "tokens": sum(r.tokens_in or 0 for r in rows) + sum(r.tokens_out or 0 for r in rows),
    }
    if gate_rows:
        scores = [p for p, _ in gate_rows]
        outcomes = [a for _, a in gate_rows]
        preds = [p >= gate_threshold for p in scores]
        ans_rows = [(p, a) for p, a in gate_rows if a]        # answerable ground truth
        unans_rows = [(p, a) for p, a in gate_rows if not a]  # unanswerable ground truth
        # FN on answerable: gate says "insufficient" (p < thr) although the corpus
        # can answer -> unnecessary hard-path escalation (the v2 failure mode that
        # drove over-abstention; here it "only" costs latency + decompose tokens).
        fn_ans = sum(1 for p, a in ans_rows if p < gate_threshold)
        # FP on unanswerable: gate says "sufficient" although the corpus cannot
        # answer -> missed escalation -> fabrication risk downstream.
        fp_unans = sum(1 for p, a in unans_rows if p >= gate_threshold)
        out["gate"] = {
            "n": len(gate_rows), "threshold": gate_threshold,
            "accuracy": round(sum(1 for pr, a in zip(preds, outcomes) if pr == a) / len(gate_rows), 4),
            "brier": round(brier_score(scores, outcomes), 4),
            "ece": round(ece(scores, outcomes), 4),
            "fn_rate_answerable": round(fn_ans / len(ans_rows), 4) if ans_rows else None,
            "fp_rate_unanswerable": round(fp_unans / len(unans_rows), 4) if unans_rows else None,
        }
    return out


def _paired(arm_rows: list[BenchResult], base_rows: list[BenchResult]) -> dict:
    base_by_q = {(r.scenario_id, r.question_id): r for r in base_rows}
    b = c = 0
    diffs: list[float] = []
    for r in arm_rows:
        ref = base_by_q.get((r.scenario_id, r.question_id))
        if ref is None:
            continue
        rc = ((r.generation or {}).get("correctness"))
        bc = ((ref.generation or {}).get("correctness"))
        if rc is None or bc is None:
            continue
        if rc > bc:
            b += 1
        elif bc > rc:
            c += 1
        diffs.append(float(rc) - float(bc))
    if not diffs:
        return {"n_paired": 0}
    boot = paired_bootstrap_ci(diffs, stat="mean", n_resamples=50000, seed=42)
    return {
        "n_paired": len(diffs),
        "mcnemar_b_arm_better": b, "mcnemar_c_base_better": c,
        "p_mcnemar": round(mcnemar_exact(b, c), 5),
        "accuracy_delta": round(boot["point"], 4),
        "accuracy_delta_ci95": [round(boot["lo"], 4), round(boot["hi"], 4)],
    }


def gate_threshold_from_config(cfg: dict | None) -> float:
    """The gate operating point a run actually used, from its recorded config.

    run_testbench.py stores the knobs NESTED under config["base"], not at the top level —
    reading them flat silently fell back to 0.5 and calibrated every published gate table
    at an operating point the run never used. Top level stays a fallback for older
    flat-config runs. 0.0 is a legitimate threshold, so absence is tested with `is None`.
    """
    cfg = cfg or {}
    base = cfg.get("base") or {}
    mode = base.get("gate_mode") or cfg.get("gate_mode") or "features"
    key = "gate_score_threshold" if mode == "features" else "jev_sufficiency_threshold"
    value = base.get(key)
    if value is None:
        value = cfg.get(key)
    return 0.5 if value is None else float(value)


def analyze(run_id: str, base: str = "base") -> dict:
    run, rows = load_rows(run_id)
    if run is None:
        raise SystemExit(f"run {run_id} not found")
    by_arm: dict[str, list[BenchResult]] = defaultdict(list)
    for r in rows:
        by_arm[r.mode].append(r)
    base_rows = by_arm.get(base)
    report: dict = {"run_id": run_id, "label": run.label, "config": run.config,
                    "base_arm": base, "arms": {}, "subsets": {}}
    pvals: dict[str, float] = {}
    # threshold semantics follow the run's gate mode (mirrors runner.py gate_analysis)
    _thr = gate_threshold_from_config(run.config if run else None)
    for arm, arows in sorted(by_arm.items()):
        stats = _arm_stats(arows, gate_threshold=_thr)
        report["arms"][arm] = stats
        if base_rows and arm != base:
            paired = _paired(arows, base_rows)
            report["arms"][arm]["vs_base"] = paired
            if paired.get("n_paired"):
                pvals[arm] = paired["p_mcnemar"]
    if pvals:
        ordered = [pvals[a] for a in sorted(pvals)]
        adjusted = bh_fdr(ordered)
        report["bh_fdr"] = {a: round(q, 5) for a, q in zip(sorted(pvals), adjusted)}
    # pre-declared subsets
    for label, ids in (("single_hop", SINGLE_HOP), ("multi_hop", MULTI_HOP)):
        sub: dict[str, list[BenchResult]] = defaultdict(list)
        for r in rows:
            if r.scenario_id in ids:
                sub[r.mode].append(r)
        if any(sub.values()):
            report["subsets"][label] = {arm: _arm_stats(ar, gate_threshold=_thr)
                                       for arm, ar in sorted(sub.items())}
    return report


def _fmt(report: dict) -> str:
    lines = [f"# Testbench report — {report['run_id']}", "",
             f"label: {report['label']}", "",
             "| arm | n | corr | 95% CI | abstain | escalate | p50 ms | cost | Δacc vs base | CI95 | McNemar p | FDR q |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    lines_gate: list[str] = []
    for arm, s in report["arms"].items():
        gate = s.get("gate")
        if gate:
            lines_gate.append(
                f"| {arm} | {gate['n']} | {gate['threshold']} | {gate['accuracy']} | "
                f"{gate['brier']} | {gate['ece']} | "
                f"{gate['fn_rate_answerable'] if gate['fn_rate_answerable'] is not None else '—'} | "
                f"{gate['fp_rate_unanswerable'] if gate['fp_rate_unanswerable'] is not None else '—'} |")
        ci = s.get("correctness_ci95_wilson")
        ci_s = f"[{ci[0]:.2f}, {ci[1]:.2f}]" if ci else ""
        abst = (s.get("abstention") or {}).get("abstained", 0)
        vs = s.get("vs_base") or {}
        delta = f"{vs.get('accuracy_delta', 0):+.3f}" if vs.get("n_paired") else "—"
        ci95 = (f"[{vs['accuracy_delta_ci95'][0]:+.3f}, {vs['accuracy_delta_ci95'][1]:+.3f}]"
                if vs.get("accuracy_delta_ci95") else "—")
        p = f"{vs.get('p_mcnemar', '—'):.3f}" if isinstance(vs.get("p_mcnemar"), float) else "—"
        q = report.get("bh_fdr", {}).get(arm)
        q_s = f"{q:.3f}" if q is not None else "—"
        esc = s.get("escalation_rate")
        lines.append(
            f"| {arm} | {s['n']} | {s.get('correctness')} | {ci_s} | {abst} | "
            f"{esc if esc is not None else '—'} | {(s.get('latency_ms') or {}).get('p50')} | "
            f"{s.get('cost_usd')} | {delta} | {ci95} | {p} | {q_s} |")
    if lines_gate:
        lines += ["", "## gate calibration (sufficiency_p vs ground-truth answerability)", "",
                  "| arm | n | thr | acc | Brier | ECE | FN(ans) | FP(unans) |",
                  "|---|---|---|---|---|---|---|---|"] + lines_gate
    for label, arms in (report.get("subsets") or {}).items():
        lines += ["", f"## subset: {label}", "",
                  "| arm | n | corr | abstain | p50 ms |", "|---|---|---|---|---|"]
        for arm, s in arms.items():
            abst = (s.get("abstention") or {}).get("abstained", 0)
            lines.append(f"| {arm} | {s['n']} | {s.get('correctness')} | {abst} | "
                         f"{(s.get('latency_ms') or {}).get('p50')} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--base", default="base")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    report = analyze(args.run_id, base=args.base)
    text = _fmt(report)
    print(text)
    if args.out:
        out = Path(args.out)
        out.write_text(text)
        out.with_suffix(".json").write_text(json.dumps(report, indent=2))
        print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
