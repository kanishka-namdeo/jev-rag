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
from app.bench.stats import bh_fdr, brier_score, mcnemar_exact, paired_bootstrap_ci, wilson_ci  # noqa: E402
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


def _arm_stats(rows: list[BenchResult]) -> dict:
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
        out["gate"] = {"n": len(gate_rows),
                       "accuracy": round(sum(1 for p, a in gate_rows if (p >= 0.5) == a) / len(gate_rows), 4),
                       "brier": round(brier_score([p for p, _ in gate_rows], [a for _, a in gate_rows]), 4)}
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
    for arm, arows in sorted(by_arm.items()):
        stats = _arm_stats(arows)
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
            report["subsets"][label] = {arm: _arm_stats(ar) for arm, ar in sorted(sub.items())}
    return report


def _fmt(report: dict) -> str:
    lines = [f"# Testbench report — {report['run_id']}", "",
             f"label: {report['label']}", "",
             "| arm | n | corr | 95% CI | abstain | escalate | p50 ms | cost | Δacc vs base | CI95 | McNemar p | FDR q |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, s in report["arms"].items():
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
