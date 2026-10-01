#!/usr/bin/env python3
"""Layer-2 pipeline testbench (cloud LLM, resumable, reaper-proof).

One-factor-at-a-time ablation arms from the v3 base config, all driving the
SAME ChatService orchestrator (arm parity is structural). Records rows in the
standard bench tables with mode = arm name and config.testbench = true.

Reaper-proof protocol (same as bench_resume.py): per-(scenario, question, arm)
atomic commits; completed triples are skipped on resume, so the driver can be
re-launched in chained tool-call windows.

Usage (from backend/):
  .venv/bin/python scripts/run_testbench.py --arms base,gate-none,gate-jev \
      [--scenarios squad,hotpotqa] [--max-per-scenario 5] [--label my-tb] \
      [--resume RUN_ID] [--window-minutes 8]

Arms (docs/testbench-design.md):
  base        v3 defaults (features gate, cross rerank)
  gate-jev    gate_mode=jev          (H-GATE: the v2 judgment, kept as an arm)
  gate-none   gate_mode=none         (H-GATE bounder: never escalate)
  always-hard escalate=True          (H-GATE bounder: always escalate)
  oracle-gate escalate=gold-in-own-top4 decision (H-GATE ceiling)
  rerank-jev  rerank_mode=jev        (H-RERANK)
  rerank-none rerank_mode=none       (H-RERANK)
  no-bestof   hybrid_best_of_n=False (H-SELECT)
  no-verify   hybrid_verify_answers=False (H-VERIFY)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: F401
from app.bench.judge import BenchJudge  # noqa: E402
from app.bench.runner import BenchRunner, _trim_memory  # noqa: E402
from app.bench.scenarios import SCENARIO_MAP  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import BenchResult, BenchRun, db_session, init_db, new_id  # noqa: E402
from app.llm.dashscope import DashscopeLLM, estimate_cost_usd  # noqa: E402
from app.llm.jev_engine import JevEngine, JevEngineUnavailable  # noqa: E402
from app.rag.crossenc import CrossEncoderReranker  # noqa: E402
from app.rag.ingestion import Ingestor  # noqa: E402
from app.rag.pipelines import ChatService  # noqa: E402
from app.rag.retriever import Embedder, VectorStore  # noqa: E402
from app.schemas import ChatRequest  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("testbench")

ARM_OVERRIDES: dict[str, dict] = {
    "base": {},
    "gate-jev": {"gate_mode": "jev"},
    "gate-none": {"gate_mode": "none"},
    "always-hard": {"_escalate": True},
    "oracle-gate": {"_escalate": "oracle"},
    "rerank-jev": {"rerank_mode": "jev"},
    "rerank-none": {"rerank_mode": "none"},
    "no-bestof": {"hybrid_best_of_n": False},
    "no-verify": {"hybrid_verify_answers": False},
}
K_ORACLE = 4  # gold-in-top-4 defines the oracle escalation decision


def _make_arm_chat(base_settings, overrides, llm, jev, embedder, store, reranker) -> ChatService:
    from app.config import Settings
    fields = {f: getattr(base_settings, f) for f in base_settings.model_fields}
    fields["_env_file"] = None
    fields.update({k: v for k, v in overrides.items() if not k.startswith("_")})
    chat = ChatService(Settings(**fields), llm, jev, embedder, store)
    chat.reranker = reranker  # ONE shared ONNX session across arms (RAM budget)
    return chat


async def run_arm_question(chat: ChatService, question, doc_ids, escalate) -> dict:
    req = ChatRequest(message=question.question, mode="hybrid", bench=True,
                      doc_ids=doc_ids, escalate=escalate)
    pre_files: list[str] = []
    files: list[str] = []
    final: dict = {}
    async for evt in chat.run(req):
        t = evt.get("type")
        if t == "retrieval":
            pre_files = [c["filename"] for c in evt.get("retrieved", [])]
        elif t == "sources":
            files = [c["filename"] for c in evt.get("citations", [])]
        elif t == "done":
            final = evt
    timings = dict(final.get("timings") or {})
    timings["latency_ms"] = final.get("latency_ms", 0.0)
    return {
        "answer": final.get("content", ""), "model": final.get("model", ""),
        "usage": final.get("usage") or {}, "context": final.get("context_used", ""),
        "files": files, "pre_files": pre_files, "timings": timings,
        "decisions": final.get("decisions") or [],
        "sufficiency_p": final.get("context_sufficiency"),
        "verification_p": final.get("verification"),
        "path": final.get("path"), "effort": final.get("effort"),
        "escalated": (final.get("gate") or {}).get("escalated"),
        "retried": final.get("retried"),
    }


def completed_triples(run_id: str) -> set[tuple[str, str, str]]:
    with db_session() as session:
        from sqlalchemy import select
        rows = session.execute(select(BenchResult).where(BenchResult.run_id == run_id)).scalars().all()
    ok: set[tuple[str, str, str]] = set()
    for r in rows:
        if not r.error:
            ok.add((r.scenario_id, r.question_id, r.mode))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default="base,gate-none,gate-jev,always-hard,oracle-gate")
    parser.add_argument("--scenarios", default="squad,hotpotqa,triviaqa,wiki2,musique")
    parser.add_argument("--max-per-scenario", type=int, default=0, help="0 = all questions")
    parser.add_argument("--label", default="")
    parser.add_argument("--resume", default="", help="existing testbench run id")
    parser.add_argument("--window-minutes", type=float, default=8.0,
                        help="stop after this much wall time (chained-window protocol)")
    args = parser.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for a in arms:
        if a not in ARM_OVERRIDES:
            print(f"unknown arm '{a}' — valid: {', '.join(ARM_OVERRIDES)}", file=sys.stderr)
            return 2
    scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    for s in scenario_ids:
        if s not in SCENARIO_MAP:
            print(f"unknown scenario {s}", file=sys.stderr)
            return 2

    settings = get_settings()
    init_db()

    if args.resume:
        run_id = args.resume
        with db_session() as session:
            run = session.get(BenchRun, run_id)
            if run is None:
                print(f"run {run_id} not found", file=sys.stderr)
                return 2
            run.status = "running"
            run.progress_stage = "resumed"
            _cfg = dict(run.config or {})
            session.commit()
        # resume-contract: when --arms/--scenarios are left at their CLI defaults,
        # adopt the RUN's recorded sets instead — a bare `--resume RUN_ID` must
        # never silently widen/narrow the experiment (same contract as the
        # bench_resume.py fix in the wave-2 docs/dev/worklog.md entries). Explicit flags always win.
        recorded = _cfg.get("arms")
        if recorded and "base,gate-none,gate-jev,always-hard,oracle-gate" == args.arms:
            arms = [a for a in recorded if a in ARM_OVERRIDES]
        recorded_scn = _cfg.get("scenarios")
        if (recorded_scn and isinstance(recorded_scn, list)
                and "squad,hotpotqa,triviaqa,wiki2,musique" == args.scenarios):
            scenario_ids = [s for s in recorded_scn if s in SCENARIO_MAP]
    else:
        with db_session() as session:
            run_id = new_id()
            session.add(BenchRun(
                id=run_id, label=args.label or f"testbench {len(arms)} arm(s)",
                status="running", scenario_ids=scenario_ids, judge_model="",
                config={"testbench": True, "arms": arms,
                        "scenarios": scenario_ids,
                        "max_per_scenario": args.max_per_scenario or "all",
                        "base": {"retrieval_mode": settings.retrieval_mode,
                                 "rerank_mode": settings.rerank_mode,
                                 "gate_mode": settings.gate_mode,
                                 "gate_score_threshold": settings.gate_score_threshold,
                                 "top_k_use": settings.top_k_use,
                                 "llm_default": settings.llm_model_default}},
                progress_total=0, progress_done=0, progress_stage="starting"))
            session.commit()

    done = completed_triples(run_id)
    logger.info("testbench %s: %d completed triples to skip", run_id, len(done))
    # Launcher contract: printed before model load so scripts/run_parallel_bench.sh
    # can capture the id seconds after launch, not after the ~17s warm-up.
    print(f"RUN_ID={run_id}", flush=True)

    # Land the denominator in the DB before anything slow happens. The monitor reads
    # done/total from bench_runs; with a cold fastembed cache the model load + corpus
    # download below takes minutes, and `0/?` for that whole window is indistinguishable
    # from a 98-question run (docs/parallel-bench-runbook.md §3).
    planned = _planned_total(scenario_ids, arms, args.max_per_scenario)
    base_done = len(done)
    _patch_run(run_id, base_done, "planning", total=planned)

    llm = DashscopeLLM(settings)
    jev = JevEngine(settings)
    if not jev.load():
        print("FATAL: jev engine failed to load", file=sys.stderr)
        return 1
    embedder = Embedder(settings)
    if not embedder.load():
        print("FATAL: embedder failed to load", file=sys.stderr)
        return 1
    store = VectorStore(settings)
    store.load()
    ingestor = Ingestor(settings, embedder, store)
    judge = BenchJudge(settings)
    runner = BenchRunner(settings, llm, jev, embedder, store, ingestor, judge)
    reranker = CrossEncoderReranker(model_name=settings.reranker_model,
                                    cache_dir=(settings.reranker_cache_dir or None))
    if settings.rerank_mode == "cross" or any(a in ("rerank-jev",) for a in arms):
        pass  # load lazily per arm chat; shared session below
    reranker.load()

    arm_chats = {a: _make_arm_chat(settings, ARM_OVERRIDES[a], llm, jev, embedder, store, reranker)
                 for a in arms}
    base_chat = arm_chats.get("base") or _make_arm_chat(settings, {}, llm, jev, embedder, store, reranker)

    deadline = time.monotonic() + args.window_minutes * 60
    t_start = time.time()
    processed = 0

    def bump(stage: str) -> None:
        _patch_run(run_id, base_done + processed, stage, total=planned)

    try:
        for sid in scenario_ids:
            if time.monotonic() > deadline:
                logger.info("window budget reached — exiting for chained resume")
                break
            scenario = SCENARIO_MAP[sid]
            doc_ids = None
            questions = scenario.questions[:args.max_per_scenario] if args.max_per_scenario else scenario.questions
            pending = [q for q in questions
                       if any((sid, q.id, a) not in done for a in arms)]
            if not pending:
                continue
            # (re)ingest the scenario corpus once
            doc_ids = asyncio.run(asyncio.to_thread(runner._reset_scenario, scenario))
            logger.info("scenario %s ready (%d docs, %d questions)", sid, len(doc_ids), len(questions))

            for q in questions:
                for arm in arms:
                    if (sid, q.id, arm) in done:
                        continue
                    if time.monotonic() > deadline:
                        bump("window-budget-reached")
                        return 0
                    chat = arm_chats[arm]
                    escalate: bool | None
                    if arm == "always-hard":
                        escalate = True
                    elif arm == "oracle-gate":
                        escalate = _oracle_decision(base_chat, q, doc_ids, settings)
                    else:
                        overrides = ARM_OVERRIDES[arm]
                        escalate = overrides.get("_escalate") if isinstance(
                            overrides.get("_escalate"), bool) else None
                    try:
                        t_q = time.time()
                        res = asyncio.run(run_arm_question(chat, q, doc_ids, escalate))
                        gen = judge.absolute(q.question, q.reference, res["context"], res["answer"])
                        judge_ms = round((time.time() - t_q - res["timings"].get("latency_ms", 0) / 1000) * 1000, 1)
                        row = BenchResult(
                            id=new_id(), run_id=run_id, scenario_id=sid, question_id=q.id,
                            question=q.question, mode=arm, qtype=q.qtype, answerable=q.answerable,
                            reference=q.reference, answer=res["answer"], model=res["model"],
                            retrieved_files=res["files"], pre_rerank_files=res["pre_files"],
                            retrieval=(retrieval_metrics_safe(res["files"], q.gold_files)),
                            generation=gen,
                            timings={**res["timings"], "judge_ms": judge_ms},
                            tokens_in=res["usage"].get("prompt_tokens", 0),
                            tokens_out=res["usage"].get("completion_tokens", 0),
                            cost_usd=estimate_cost_usd(res["model"],
                                                       res["usage"].get("prompt_tokens", 0),
                                                       res["usage"].get("completion_tokens", 0)),
                            sufficiency_p=res["sufficiency_p"],
                            verification_p=res["verification_p"],
                            routed_model=res["model"], jev_decisions=res["decisions"],
                        )
                        with db_session() as session:
                            session.add(row)
                            session.commit()
                        processed += 1
                        logger.info("[%s/%s/%s] path=%s corr=%s (%.0fs)", arm, sid, q.id,
                                    res["path"], (gen or {}).get("correctness"),
                                    time.time() - t_q)
                    except JevEngineUnavailable as e:
                        logger.warning("engine unavailable at %s/%s/%s — 20s grace retry", arm, sid, q.id)
                        time.sleep(20)
                        try:
                            bump(f"engine-retry {sid}/{q.id}/{arm}")
                            # retry once inline
                            res = asyncio.run(run_arm_question(chat, q, doc_ids, escalate))
                        except Exception as e2:  # noqa: BLE001
                            _persist_error(run_id, sid, q, arm, e2)
                            continue
                    except Exception as e:  # noqa: BLE001
                        logger.exception("arm question failed: %s/%s/%s", arm, sid, q.id)
                        _persist_error(run_id, sid, q, arm, e)
                    _trim_memory()
                    bump(f"{sid}/{q.id}/{arm}")
        bump("completed")
    except KeyboardInterrupt:
        bump("interrupted")

    print(f"\nrun_id: {run_id}  processed: {processed} "
          f"(run total {base_done + processed}/{planned})  "
          f"elapsed: {(time.time()-t_start)/60:.1f} min")
    print("resume with:  .venv/bin/python scripts/run_testbench.py --resume " + run_id)
    return 0


def _oracle_decision(base_chat: ChatService, q, doc_ids, settings) -> bool:
    """Perfect-retry bounder: escalate iff gold files are NOT all in the arm's
    own RRF+rerank top-4 (computable without any LLM call)."""
    try:
        pool, _ms = base_chat._retrieve(q.question, settings.top_k_retrieve, doc_ids)
        ranked, _rec = base_chat._rerank(q.question, pool)
        kept = ranked[: settings.top_k_use]
        kept_files = {c["filename"] for c in kept}
        gold = set(q.gold_files)
        return not gold.issubset(kept_files)
    except Exception:  # noqa: BLE001
        return True  # escalate on uncertainty


def retrieval_metrics_safe(files: list[str], gold: list[str]) -> dict:
    if not gold:
        return {}
    from app.bench.metrics import retrieval_metrics
    return retrieval_metrics(files, gold)


def _planned_total(scenario_ids: list[str], arms: list[str],
                   max_per_scenario: int) -> int:
    """Triples this invocation intends to score — the monitor's denominator."""
    total = 0
    for sid in scenario_ids:
        questions = SCENARIO_MAP[sid].questions
        if max_per_scenario:
            questions = questions[:max_per_scenario]
        total += len(questions) * len(arms)
    return total


def _patch_run(run_id: str, done: int, stage: str, total: int | None = None) -> None:
    with db_session() as session:
        run = session.get(BenchRun, run_id)
        if run is None:
            return
        run.progress_done = done
        run.progress_stage = stage
        if total is not None:
            run.progress_total = total
        if stage == "completed":
            run.status = "completed"
            run.finished_at = datetime.now(timezone.utc)
        session.commit()


def _persist_error(run_id: str, sid: str, q, arm: str, exc: Exception) -> None:
    with db_session() as session:
        session.add(BenchResult(
            id=new_id(), run_id=run_id, scenario_id=sid, question_id=q.id,
            question=q.question, mode=arm, qtype=q.qtype, answerable=q.answerable,
            reference=q.reference, answer="", model="",
            error=f"{type(exc).__name__}: {exc}"))
        session.commit()


if __name__ == "__main__":
    raise SystemExit(main())
