#!/usr/bin/env python3
"""analyze_per_scenario.py — per-scenario two-arm summary for a bench run.

Correctness: binary@0.5 (judge score >= 0.5 counts correct, the suite's
headline yardstick) + mean judge score. Retrieval: file-level recall@4 /
hit@4 from the stored retrieval JSON. Latency p50 per arm; cost; hybrid
sufficiency-gate calibration (accuracy vs answerable ground truth + Brier).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db import db_session, BenchResult
from sqlalchemy import select


def pct(x, n):
    return round(100.0 * x / n, 1) if n else 0.0


def main(run_id: str) -> None:
    with db_session() as s:
        rows = s.execute(
            select(BenchResult).where(BenchResult.run_id == run_id)
        ).scalars().all()

    by_scen: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.error:
            continue
        by_scen[r.scenario_id][r.mode].append(r)

    out: dict = {}
    for scen, modes in sorted(by_scen.items()):
        d: dict = {"n_questions": len(modes["traditional"])}
        for mode in ("traditional", "hybrid"):
            rs = modes[mode]
            scores = [(r.generation or {}).get("correctness", 0.0) for r in rs]
            n_ok = sum(1 for c in scores if c >= 0.5)
            d[mode] = {
                "binary@0.5": pct(n_ok, len(rs)),
                "mean_correctness": round(sum(scores) / len(scores), 3),
                "faithfulness": round(
                    sum((r.generation or {}).get("faithfulness", 0.0) for r in rs) / len(rs), 3),
            }
            # retrieval metrics (file-level, precomputed per row)
            rec, hit, nn = [], [], 0
            for r in rs:
                ret = r.retrieval or {}
                if "recall4" in ret:
                    rec.append(float(ret["recall4"]))
                    hit.append(float(ret.get("hit4", 0)))
                    nn += 1
            if nn:
                d[mode]["recall@4"] = round(100 * sum(rec) / nn, 1)
                d[mode]["hit@4"] = round(100 * sum(hit) / nn, 1)
            # latency + cost
            lat = [(r.timings or {}).get("latency_ms") for r in rs
                   if (r.timings or {}).get("latency_ms")]
            if lat:
                d[mode]["latency_p50_s"] = round(median(lat) / 1000, 1)
                d[mode]["latency_mean_s"] = round(sum(lat) / len(lat) / 1000, 1)
            cost = [r.cost_usd for r in rs if r.cost_usd is not None]
            if cost:
                d[mode]["cost_usd_mean"] = round(sum(cost) / len(cost), 4)
        # hybrid gate calibration (all these questions are answerable)
        sufs = [(r.sufficiency_p, True) for r in modes["hybrid"] if r.sufficiency_p is not None]
        if sufs:
            thr = 0.5
            acc = sum(1 for p, y in sufs if (p >= thr) == y) / len(sufs)
            brier = sum((p - (1 if y else 0)) ** 2 for p, y in sufs) / len(sufs)
            d["gate"] = {"n": len(sufs), "accuracy@0.5": round(acc, 3),
                         "brier": round(brier, 3),
                         "mean_p": round(sum(p for p, _ in sufs) / len(sufs), 3)}
        # pairwise per scenario
        pw = defaultdict(int)
        for r in modes["hybrid"]:
            v = (r.pairwise or {}).get("winner")
            pw[v or "?"] += 1
        pos = [(r.pairwise or {}).get("position_consistent") for r in modes["hybrid"]]
        pos_ok = sum(1 for p in pos if p)
        d["pairwise"] = {**dict(pw), "position_consistent": f"{pos_ok}/{len(pos)}"}
        out[scen] = d

    print(json.dumps(out, indent=1))
    # compact table
    print(f"\n{'scenario':10} {'n':>3} {'trad@0.5':>9} {'hyb@0.5':>8} {'delta':>7} "
          f"{'tradRec@4':>9} {'hybRec@4':>8} {'tP50':>5} {'hP50':>5}")
    for scen, d in out.items():
        t, h = d["traditional"], d["hybrid"]
        print(f"{scen:10} {d['n_questions']:>3} {t['binary@0.5']:>8}% {h['binary@0.5']:>7}% "
              f"{round(h['binary@0.5'] - t['binary@0.5'], 1):>+6}pp "
              f"{t.get('recall@4', 0):>8}% {h.get('recall@4', 0):>7}% "
              f"{t.get('latency_p50_s', 0):>5} {h.get('latency_p50_s', 0):>5}")


if __name__ == "__main__":
    main(sys.argv[1])
