#!/usr/bin/env python3
"""bench_progress.py — quick progress readout for a bench run."""
import sys
sys.path.insert(0, "/home/z/my-project/backend")
from app.db import db_session, BenchRun, BenchResult
from sqlalchemy import select
from collections import Counter

run_id = sys.argv[1] if len(sys.argv) > 1 else ""
with db_session() as s:
    if run_id:
        runs = [s.get(BenchRun, run_id)]
    else:
        runs = s.execute(select(BenchRun).order_by(BenchRun.created_at.desc())).scalars().all()
    for run in runs:
        if run is None:
            continue
        rows = s.execute(select(BenchResult).where(BenchResult.run_id == run.id)).scalars().all()
        ok = Counter()
        err = 0
        scen = Counter()
        for r in rows:
            if r.error:
                err += 1
            else:
                ok[r.mode] += 1
            scen[r.scenario_id] += 1
        print(f"run {run.id} [{run.status}] '{run.label[:60]}'")
        print(f"  stage: {run.progress_stage} | done {run.progress_done}/{run.progress_total}")
        print(f"  rows: trad={ok['traditional']} hybrid={ok['hybrid']} errors={err} | per-scenario {dict(scen)}")
