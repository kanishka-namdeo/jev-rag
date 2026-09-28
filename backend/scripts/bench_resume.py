#!/usr/bin/env python3
"""bench_resume.py — resumable driver for the audited benchmark harness.

Why this exists
---------------
The sandbox reaper kills any user process seconds after its spawning tool call
ends, so a 90-minute uvicorn-hosted benchmark run cannot survive. This driver
runs the SAME audited per-question code path (BenchRunner._run_question: both
arms, independent judge, pairwise) as a plain foreground process and
checkpoints after EVERY question to SQLite. Killed at any point, the next
invocation with the same --run-id picks up exactly where it stopped (questions
whose rows are committed are skipped; ingestion is reused when the scenario's
docs are already in the store).

Protocol parity with the HTTP-driven runner (docs/benchmarking.md):
- identical arms, prompts, chunking, embeddings, knobs (same BenchRunner)
- judge self-test (8 canaries) recorded at run creation
- identical config snapshot written to the run row
- per-question atomic commit (both arms + pairwise land together or not at all)

Usage:
  cd backend && .venv/bin/python scripts/bench_resume.py \
      [--run-id ID] [--scenarios squad,hotpotqa] [--label "..."] \
      [--max-minutes 8] [--smoke]
Exit code 0 on clean pause/finish; rows in SQLite carry all state.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ root

from sqlalchemy import select

import app  # noqa: F401  (package init)
from app.bench.judge import BenchJudge
from app.bench.runner import BenchRunner, _trim_memory
from app.bench.scenarios import SCENARIO_MAP
from app.config import get_settings
from app.db import BenchResult, BenchRun, Document, db_session, init_db, new_id
from app.llm.dashscope import DashscopeLLM
from app.llm.jev_engine import JevEngine
from app.rag.ingestion import Ingestor
from app.rag.pipelines import ChatService, SUFFICIENCY_THRESHOLD  # noqa: F401
from app.rag.retriever import Embedder, VectorStore

logger = logging.getLogger("jevrag.bench.resume")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- run row handling
def create_run(runner: BenchRunner, scenario_ids: list[str], label: str) -> str:
    """Mirror of BenchRunner.start()'s row creation (same config snapshot)."""
    s = runner.settings
    scenarios = [SCENARIO_MAP[i] for i in scenario_ids]
    total_q = sum(len(sc.questions) for sc in scenarios)
    with db_session() as session:
        run = BenchRun(
            id=new_id(),
            label=label or f"bench {len(scenarios)} scenario(s)",
            status="queued",
            scenario_ids=scenario_ids,
            judge_model=runner.judge.model,
            config={
                "pipeline": "hybrid-v2",
                "top_k_retrieve": s.top_k_retrieve,
                "top_k_use": s.top_k_use,
                "llm_default": s.llm_model_default,
                "llm_reasoning": s.llm_model_reasoning,
                "pairwise": s.bench_pairwise,
                "sufficiency_threshold": SUFFICIENCY_THRESHOLD,
                "effort_routing": s.hybrid_effort_routing,
                "passage_battery": s.hybrid_passage_battery,
                "corrective_retry": s.hybrid_corrective_retry,
                "best_of_n": s.hybrid_best_of_n,
                "citation_verify": s.hybrid_citation_verify,
                "jev_model": "jev-style-0.8b-decision-v3",
                "embed_model": s.embed_model,
                "question_limit_per_scenario": "all",
                "driver": "bench_resume.py (resumable, sandbox-reaper-proof)",
            },
            progress_total=total_q,
            progress_done=0,
            progress_stage="queued",
        )
        session.add(run)
        session.commit()
        return run.id


def completed_questions(run_id: str) -> set[tuple[str, str]]:
    """(scenario_id, question_id) pairs with both arms committed and error-free."""
    with db_session() as session:
        rows = session.execute(
            select(BenchResult).where(BenchResult.run_id == run_id)
        ).scalars().all()
    ok: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        key = (r.scenario_id, r.question_id)
        ok.setdefault(key, set())
        if not r.error:
            ok[key].add(r.mode)
    return {k for k, modes in ok.items() if {"traditional", "hybrid"} <= modes}


def existing_doc_ids(filenames: list[str]) -> list[str] | None:
    """All scenario docs already ingested and ready -> reuse (skip re-ingest)."""
    with db_session() as session:
        docs = session.execute(
            select(Document).where(Document.filename.in_(filenames))
        ).scalars().all()
    if len(docs) != len(filenames):
        return None
    by_name = {d.filename: d for d in docs}
    if any(d.status != "ready" for d in docs):
        return None
    # duplicate copies of a filename would poison the doc_ids filter
    names = [d.filename for d in docs]
    if len(names) != len(set(names)):
        return None
    return [by_name[f].id for f in filenames]


# ---------------------------------------------------------------- main loop
async def drive(runner: BenchRunner, run_id: str, scenarios, deadline: float,
                smoke: bool) -> bool:
    """Run remaining questions; returns True when the run is complete."""
    done_before = completed_questions(run_id)
    logger.info("resume state: %d questions already complete", len(done_before))

    with db_session() as session:
        run = session.get(BenchRun, run_id)
        run.status = "running"
        run.started_at = run.started_at or _now()
        session.commit()

    total = sum(len(sc.questions) for sc in scenarios)
    for scenario in scenarios:
        doc_ids = existing_doc_ids(list(scenario.docs))
        if doc_ids is None:
            logger.info("scenario '%s': (re)ingesting %d docs",
                        scenario.id, len(scenario.docs))
            runner._patch_run(run_id, progress_stage=f"ingesting scenario '{scenario.id}'")
            doc_ids = await asyncio.to_thread(runner._reset_scenario, scenario)
        else:
            logger.info("scenario '%s': reusing %d ingested docs",
                        scenario.id, len(doc_ids))

        for q in scenario.questions:
            if (scenario.id, q.id) in done_before:
                continue
            if time.monotonic() > deadline:
                runner._patch_run(run_id, progress_stage="paused (resumable — deadline)")
                logger.info("soft deadline reached — pausing; re-run to resume")
                return False
            if smoke and len(completed_questions(run_id)) >= 2:
                runner._patch_run(run_id, progress_stage="smoke complete")
                return True

            runner._patch_run(run_id, progress_stage=f"[{scenario.id}] question {q.id}")
            t0 = time.perf_counter()
            try:
                await runner._run_question(run_id, scenario, q, doc_ids)
            except Exception as e:  # noqa: BLE001 — per-question isolation
                logger.exception("question %s/%s failed", scenario.id, q.id)
                runner._persist_error(run_id, scenario, q, e)
            dt = time.perf_counter() - t0
            done = len(completed_questions(run_id))
            logger.info("[%s] %s done in %.1fs — %d/%d", scenario.id, q.id, dt, done, total)
            runner._patch_run(run_id, progress_done=done)
            _trim_memory()

    runner._patch_run(run_id, progress_stage="aggregating")
    summary = await asyncio.to_thread(runner._summarize, run_id)
    runner._patch_run(run_id, status="completed", finished_at=_now(),
                      summary=summary, progress_stage="completed")
    logger.info("run %s COMPLETE", run_id)
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="", help="resume this run (omit to create)")
    ap.add_argument("--scenarios", default="",
                    help="comma-separated scenario ids; REQUIRED for new runs, "
                         "defaults to the run's stored scenario_ids when resuming")
    ap.add_argument("--label", default="")
    ap.add_argument("--max-minutes", type=float, default=8.0,
                    help="soft deadline from process start; exits cleanly before it")
    ap.add_argument("--smoke", action="store_true", help="stop after 2 questions")
    args = ap.parse_args()

    deadline = time.monotonic() + args.max_minutes * 60

    settings = get_settings()
    init_db()
    t0 = time.perf_counter()
    store = VectorStore(settings); store.load()
    embedder = Embedder(settings); embedder.load()
    jev = JevEngine(settings)
    if not jev.load():
        raise SystemExit(f"FATAL: jev engine failed to load: {jev._load_error}")
    llm = DashscopeLLM(settings)
    ingestor = Ingestor(settings, embedder, store)
    judge = BenchJudge(settings)
    runner = BenchRunner(settings, llm, jev, embedder, store, ingestor, judge)
    logger.info("models ready in %.1fs (jev: %s)", time.perf_counter() - t0,
                jev.info().get("model"))

    if args.run_id:
        run_id = args.run_id
        with db_session() as session:
            run = session.get(BenchRun, run_id)
        if run is None:
            raise SystemExit(f"FATAL: run {run_id} not found")
        if run.status == "completed":
            print(json_summary(run_id))
            raise SystemExit(0)
        # resume defaults to the run's own scenario list (a stale CLI default
        # here once contaminated a run with off-plan scenarios)
        scenario_ids = [s.strip() for s in (args.scenarios or ",".join(run.scenario_ids)).split(",") if s.strip()]
    else:
        if not args.scenarios:
            raise SystemExit("FATAL: --scenarios is required for new runs")
        scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
        run_id = create_run(runner, scenario_ids, args.label)
        runner._patch_run(run_id, judge_selftest=judge.self_test())
        logger.info("run %s created; judge self-test done", run_id)
    unknown = [s for s in scenario_ids if s not in SCENARIO_MAP]
    if unknown:
        raise SystemExit(f"FATAL: unknown scenarios: {unknown}")
    print(f"RUN_ID={run_id}", flush=True)

    scenarios = [SCENARIO_MAP[s] for s in scenario_ids]
    complete = asyncio.run(drive(runner, run_id, scenarios, deadline, args.smoke))
    if complete:
        print(json_summary(run_id))


def json_summary(run_id: str) -> str:
    import json
    with db_session() as session:
        run = session.get(BenchRun, run_id)
    if run is None:
        return "{}"
    return json.dumps({"run_id": run_id, "status": run.status,
                       "label": run.label, "summary": run.summary}, indent=2)[:4000]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    main()
