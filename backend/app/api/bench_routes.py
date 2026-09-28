"""Benchmark API routes: scenario catalog, run lifecycle, results."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.bench.runner import RunConflictError
from app.bench.scenarios import SCENARIOS
from app.db import BenchResult, BenchRun, db_session

logger = logging.getLogger("jevrag.api.bench")

router = APIRouter(prefix="/bench")


class RunCreateRequest(BaseModel):
    scenario_ids: list[str] = Field(min_length=1)
    label: str = ""
    # optional per-run question cap (smoke runs); None -> settings default (0 = all)
    max_questions: int | None = Field(default=None, ge=1)


def _runner(request):
    return request.app.state.bench_runner


def _run_out(r: BenchRun, lite: bool = True) -> dict:
    out = {
        "id": r.id, "label": r.label, "status": r.status,
        "scenario_ids": r.scenario_ids or [],
        "judge_model": r.judge_model,
        "config": r.config,
        "progress": {"done": r.progress_done, "total": r.progress_total,
                     "stage": r.progress_stage},
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "started_at": r.started_at.isoformat() if r.started_at else "",
        "finished_at": r.finished_at.isoformat() if r.finished_at else "",
        "error": r.error,
    }
    if not lite:
        out["judge_selftest"] = r.judge_selftest
        out["summary"] = r.summary
    return out


# ---------------------------------------------------------------- scenarios
@router.get("/scenarios")
async def list_scenarios():
    return {"scenarios": [s.meta() for s in SCENARIOS]}


# ---------------------------------------------------------------- runs
@router.post("/runs")
async def create_run(req: RunCreateRequest, request: Request):
    runner = _runner(request)
    try:
        run_id = runner.start(req.scenario_ids, req.label,
                              max_questions=req.max_questions)
    except RunConflictError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    with db_session() as session:
        run = session.get(BenchRun, run_id)
        return {"run": _run_out(run)}


@router.get("/runs")
async def list_runs(request: Request):
    runner = _runner(request)
    with db_session() as session:
        runs = session.execute(
            select(BenchRun).order_by(BenchRun.created_at.desc()).limit(50)).scalars().all()
        return {"runs": [_run_out(r) for r in runs], "runner_active": runner.active}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    with db_session() as session:
        run = session.get(BenchRun, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        results = session.execute(
            select(BenchResult).where(BenchResult.run_id == run_id)
            .order_by(BenchResult.scenario_id, BenchResult.question_id, BenchResult.mode)
        ).scalars().all()
        return {
            "run": _run_out(run, lite=False),
            "results": [_result_out(r) for r in results],
        }


def _result_out(r: BenchResult) -> dict:
    return {
        "id": r.id, "run_id": r.run_id, "scenario_id": r.scenario_id,
        "question_id": r.question_id, "question": r.question, "mode": r.mode,
        "qtype": r.qtype, "answerable": r.answerable, "reference": r.reference,
        "answer": r.answer, "model": r.model, "error": r.error,
        "retrieved_files": r.retrieved_files or [],
        "pre_rerank_files": r.pre_rerank_files or [],
        "retrieval": r.retrieval or {},
        "naive_retrieval": r.naive_retrieval or {},
        "generation": r.generation or {},
        "pairwise": r.pairwise,
        "timings": r.timings or {},
        "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
        "cost_usd": r.cost_usd,
        "sufficiency_p": r.sufficiency_p, "verification_p": r.verification_p,
        "routed_model": r.routed_model,
    }


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, request: Request):
    runner = _runner(request)
    with db_session() as session:
        run = session.get(BenchRun, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run.status in ("queued", "running", "cancelling") and runner.active:
            if run.status == "cancelling":
                raise HTTPException(409, "run is already cancelling — wait for it to stop")
            # ask the runner to stop at the next question boundary
            run.status = "cancelling"
            session.commit()
            return {"run": _run_out(run), "cancelling": True}
        results = session.execute(
            select(BenchResult).where(BenchResult.run_id == run_id)).scalars().all()
        for r in results:
            session.delete(r)
        session.delete(run)
        session.commit()
    return {"deleted": run_id}
