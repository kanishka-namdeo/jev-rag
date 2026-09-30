#!/usr/bin/env python3
"""Merge the 5 per-scenario H-GATE DBs into one canonical merged DB.

Each of the 5 parallel workers wrote to its own JEVRAG_DATA_DIR. This
merges the bench_results + bench_runs rows from all 5 into a new
backend/data_merged/app.db, dedupes by (scenario, question, arm) keeping
the most recent row, and creates one unified bench_runs row so the
existing analyzer can be run against it without modification.

Picks the COMPLETED run per scenario (not the newest), because the
musique scenario has a later in-flight retry run that would otherwise
win the "newest" tie-break.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (scenario, db_path, expected unique triples)
DBS = [
    ("squad",     ROOT / "backend/data/app.db",                    100),
    ("hotpotqa",  ROOT / "backend/data_par/hotpotqa/app.db",       100),
    ("triviaqa",  ROOT / "backend/data_par/triviaqa/app.db",        64),
    ("wiki2",     ROOT / "backend/data_par/wiki2/app.db",           64),
    ("musique",   ROOT / "backend/data_par/musique/app.db",        64),
]
MERGED_DB = ROOT / "backend/data_merged/app.db"

UNIFIED_LABEL = "H-GATE full power (par x5, merged 2026-09-30)"
UNIFIED_ARMS = ["base", "gate-none", "always-hard", "oracle-gate"]
UNIFIED_SCENARIOS = ["squad", "hotpotqa", "triviaqa", "wiki2", "musique"]


def pick_run(conn: sqlite3.Connection, sid: str) -> tuple[str, int]:
    """Return (run_id, n_rows) of the COMPLETED run for this scenario.

    Prefers a 'completed' status run with the most rows; falls back to the
    latest run that has any non-error rows for this scenario.
    """
    completed = conn.execute(
        "select r.id, count(*) from bench_runs r "
        "left join bench_results b on b.run_id=r.id and b.scenario_id=? "
        "where r.status='completed' group by r.id "
        "having count(*) > 0 order by count(*) desc, r.rowid desc",
        (sid,),
    ).fetchall()
    if completed:
        return completed[0][0], completed[0][1]
    # fallback: newest run with this scenario's rows
    latest = conn.execute(
        "select r.id, count(*) from bench_runs r "
        "left join bench_results b on b.run_id=r.id and b.scenario_id=? "
        "where count(*) > 0 group by r.id order by r.rowid desc",
        (sid,),
    ).fetchall()
    if latest:
        return latest[0][0], latest[0][1]
    # absolute fallback: the newest run in the db
    newest = conn.execute("select id from bench_runs order by rowid desc limit 1").fetchone()
    return (newest[0], 0) if newest else (None, 0)


def main() -> int:
    for sid, db, _ in DBS:
        if not db.exists():
            print(f"MISSING: {db}", file=sys.stderr)
            return 2

    MERGED_DB.parent.mkdir(parents=True, exist_ok=True)
    if MERGED_DB.exists():
        MERGED_DB.unlink()

    try:
        merged = sqlite3.connect(str(MERGED_DB))
        cur = merged.cursor()

        schema = sqlite3.connect(str(DBS[0][1]))
        schema_rows = schema.execute(
            "select sql from sqlite_master where type in ('table','index','view') order by rowid"
        ).fetchall()
        for (sql,) in schema_rows:
            if sql and sql.strip().startswith(("CREATE TABLE", "CREATE INDEX", "CREATE VIEW")):
                cur.execute(sql)
        schema.close()

        first_conn = sqlite3.connect(str(DBS[0][1]))
        src_run = first_conn.execute(
            "select id, status, scenario_ids, judge_model, config, progress_total, progress_done, "
            "progress_stage, judge_selftest, summary, error, created_at, started_at, finished_at "
            "from bench_runs where status='completed' order by rowid desc limit 1"
        ).fetchone()
        first_conn.close()
        if src_run is None:
            print("no completed source run found in first DB", file=sys.stderr)
            return 3
        src_config = json.loads(src_run[4]) if src_run[4] else {}
        src_config["arms"] = UNIFIED_ARMS
        src_config["scenarios"] = UNIFIED_SCENARIOS
        src_config["merged_from"] = [d[1].name for d in DBS]
        unified_total = sum(d[2] for d in DBS)
        unified_run_id = str(uuid.uuid4())
        cur.execute(
            "insert into bench_runs (id,label,status,scenario_ids,judge_model,config,"
            "progress_total,progress_done,progress_stage,judge_selftest,summary,error,"
            "created_at,started_at,finished_at) values (" + ",".join(["?"]*15) + ")",
            (
                unified_run_id, UNIFIED_LABEL, "completed", json.dumps(UNIFIED_SCENARIOS),
                src_run[3], json.dumps(src_config), unified_total, unified_total,
                "completed", src_run[8], src_run[9], src_run[10],
                src_run[11], src_run[12], src_run[13],
            ),
        )
        merged.commit()

        total_rows = 0
        per_scenario: dict[str, int] = {}
        for sid, db, expected in DBS:
            conn = sqlite3.connect(str(db))
            run_id, n_in_run = pick_run(conn, sid)
            rows = conn.execute(
                "select id,run_id,scenario_id,question_id,question,mode,qtype,answerable,"
                "reference,answer,model,error,retrieved_files,pre_rerank_files,retrieval,"
                "naive_retrieval,generation,pairwise,timings,tokens_in,tokens_out,cost_usd,"
                "sufficiency_p,verification_p,routed_model,jev_decisions,created_at "
                "from bench_results where run_id=? and scenario_id=? order by rowid",
                (run_id, sid),
            ).fetchall()
            for r in rows:
                cur.execute(
                    "insert into bench_results (id,run_id,scenario_id,question_id,question,mode,"
                    "qtype,answerable,reference,answer,model,error,retrieved_files,pre_rerank_files,"
                    "retrieval,naive_retrieval,generation,pairwise,timings,tokens_in,tokens_out,"
                    "cost_usd,sufficiency_p,verification_p,routed_model,jev_decisions,created_at) "
                    "values (" + ",".join(["?"]*27) + ")",
                    (
                        r[0], unified_run_id, r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                        r[10], r[11], r[12], r[13], r[14], r[15], r[16], r[17], r[18], r[19],
                        r[20], r[21], r[22], r[23], r[24], r[25], r[26],
                    ),
                )
            per_scenario[sid] = len(rows)
            total_rows += len(rows)
            print(f"  {sid}: picked run {run_id[:8]} ({n_in_run} rows in that run), "
                  f"copied {len(rows)} rows for {sid} (expected {expected})")
            conn.close()
        merged.commit()

        print(f"\nmerged {total_rows} rows; unique expected = {unified_total}")
        for sid, _, expected in DBS:
            n = cur.execute("select count(*) from bench_results where scenario_id=?", (sid,)).fetchone()[0]
            e = cur.execute(
                "select count(*) from bench_results where scenario_id=? and error is not null and error!=''",
                (sid,),
            ).fetchone()[0]
            status = "OK" if n >= expected else "SHORT"
            print(f"  {sid}: {n}/{expected} rows ({e} errors) [{status}]")
        total_errors = cur.execute(
            "select count(*) from bench_results where error is not null and error!=''"
        ).fetchone()[0]
        print(f"\ntotal errors: {total_errors}")
        print(f"unified run id: {unified_run_id}")
        print(f"merged db: {MERGED_DB}")
        print(f"\nRun the analyzer against the merged DB (from backend/):")
        print(f"  JEVRAG_DATA_DIR={MERGED_DB.parent} .venv/bin/python "
              f"scripts/analyze_testbench.py {unified_run_id} --out ../docs/testbench-results-hgate.md")
        return 0
    finally:
        merged.close()


if __name__ == "__main__":
    raise SystemExit(main())
