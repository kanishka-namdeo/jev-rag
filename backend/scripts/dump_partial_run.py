#!/usr/bin/env python3
"""Dump a (possibly partial) testbench run's result rows to a repo-committable JSON.

Usage: backend/.venv/bin/python scripts/dump_partial_run.py <run_id> <out.json>
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402
from app.db import BenchResult, BenchRun, db_session  # noqa: E402


def main() -> int:
    run_id, out_path = sys.argv[1], sys.argv[2]
    with db_session() as s:
        run = s.get(BenchRun, run_id)
        if run is None:
            print(f"run {run_id} not found")
            return 1
        rows = s.execute(
            select(BenchResult).where(BenchResult.run_id == run_id)
            .order_by(BenchResult.scenario_id, BenchResult.question_id, BenchResult.mode)
        ).scalars().all()
        payload = {
            "run": {
                "id": run.id, "label": run.label, "status": run.status,
                "scenario_ids": run.scenario_ids, "config": run.config,
                "progress_stage": run.progress_stage,
                "progress_done": run.progress_done,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            },
            "row_count": len(rows),
            "partial": run.status != "completed",
            "rows": [
                {
                    "scenario": r.scenario_id, "question_id": r.question_id,
                    "question": r.question, "arm": r.mode, "qtype": r.qtype,
                    "answerable": r.answerable, "reference": r.reference,
                    "answer": r.answer, "model": r.model,
                    "retrieved_files": r.retrieved_files,
                    "pre_rerank_files": r.pre_rerank_files,
                    "retrieval": r.retrieval, "generation": r.generation,
                    "timings": r.timings,
                    "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                    "cost_usd": r.cost_usd, "error": r.error,
                }
                for r in rows
            ],
        }
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"wrote {out_path}: {len(rows)} rows (status={run.status})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
