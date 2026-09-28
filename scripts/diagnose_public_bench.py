#!/usr/bin/env python3
"""diagnose_public_bench.py — per-question loss/win taxonomy for the public
benchmark run: which arm won, was it an abstention flip, gate probability."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import json
from app.db import BenchResult, db_session, init_db

RUN = sys.argv[1] if len(sys.argv) > 1 else "4dc6c46e-a566-4134-ab9d-a59a653564e5"

init_db()
with db_session() as s:
    rows = s.query(BenchResult).filter(BenchResult.run_id == RUN).all()

by_q: dict[tuple, dict[str, BenchResult]] = {}
for r in rows:
    by_q.setdefault((r.scenario_id, r.question_id), {})[r.mode] = r

print(f"{'scen/q':12} {'T':>14} {'H':>14} {'verdict':18} notes")
losses = []
for (sc, qid), arms in sorted(by_q.items()):
    t, h = arms["traditional"], arms["hybrid"]
    tc = t.generation["correctness"] if t.generation else None
    hc = h.generation["correctness"] if h.generation else None
    t_ab = t.generation.get("abstention", "?") if t.generation else "?"
    h_ab = h.generation.get("abstention", "?") if h.generation else "?"
    diff = (hc or 0) - (tc or 0)
    if diff < -0.4:
        verdict = "TRAD WIN"
        losses.append((sc, qid, t, h))
    elif diff > 0.4:
        verdict = "HYBRID WIN"
    else:
        continue  # skip ties for compactness
    print(f"{sc[:4]}/{qid:5} {tc!s:>5} ({t_ab[:4]}) {hc!s:>5} ({h_ab[:4]}) {verdict:18}")

print("\n=== hybrid-loss detail (correctness diff < -0.4) ===")
for sc, qid, t, h in losses:
    print(f"\n--- {sc}/{qid}: {h.question[:90]}")
    print(f"  ref: {h.reference[:90]}")
    print(f"  trad ({t.generation.get('abstention')}): {t.answer[:120]!r}")
    print(f"  hyb  ({h.generation.get('abstention')}): {h.answer[:120]!r}")
    print(f"  hyb sufficiency_p={h.sufficiency_p} verification_p={h.verification_p}")
    print(f"  hyb files={[f for f in (h.retrieved_files or [])][:4]}")
    print(f"  trad files={[f for f in (t.retrieved_files or [])][:4]}")
    dec = (h.jev_decisions or [])
    for d in dec[:3]:
        print(f"    dec: {d.get('name', '?')} -> {str(d.get('answer'))[:80]}")

# gate calibration per scenario
print("\n=== sufficiency gate (hybrid arm) per scenario ===")
for scen in ("squad", "hotpotqa"):
    sufs = [r.sufficiency_p for r in rows
            if r.scenario_id == scen and r.mode == "hybrid" and r.sufficiency_p is not None]
    abst = sum(1 for r in rows
               if r.scenario_id == scen and r.mode == "hybrid"
               and r.generation and r.generation.get("abstention") == "abstained")
    low = [p for p in sufs if p is not None and p < 0.5]
    print(f"  {scen}: n={len(sufs)} mean_p={sum(sufs)/len(sufs):.3f} "
          f"below-0.5={len(low)} abstained={abst}")
