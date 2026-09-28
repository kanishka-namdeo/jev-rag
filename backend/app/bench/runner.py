"""Benchmark orchestration: ingest scenario -> run BOTH pipelines -> judge -> aggregate.

Fairness protocol (docs/benchmarking.md):
- Both arms answer the SAME questions over the SAME corpus snapshot with the SAME
  prompts, chunking, embeddings and knobs as the production pipelines — because
  both arms are driven through the SAME ChatService orchestrator
  (pipelines.ChatService.run with bench=True): there is exactly ONE pipeline
  implementation in the codebase, so arm parity is structural, not maintained
  by hand (this replaced the pre-v3 hand-mirrored `_arm_*` methods).
- Matched final context budget: BOTH arms retrieve top_k_retrieve=10 RRF
  candidates, rerank (same slot, same budget), and keep top_k_use=4.
- The judge model is independent of both arms' generators (no self-preference bias).
- Hybrid additionally records pre-rerank metrics -> rerank lift, and its sufficiency
  gate probability -> gate accuracy/Brier vs ground-truth answerability.

The runner executes inside the FastAPI process (survives the sandbox reaper) as a
single sequential asyncio task — the Jev engine is a single subprocess, so runs are
serialized by design. Only one run may be active at a time.
"""
from __future__ import annotations

import asyncio
import ctypes
import gc
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select

from app.bench.judge import BenchJudge
from app.bench.metrics import agg_retrieval, brier, pct, retrieval_metrics
from app.bench.scenarios import SCENARIO_MAP, BenchQuestion, BenchScenario, doc_path
from app.config import Settings
from app.db import BenchResult, BenchRun, db_session, new_id
from app.llm.dashscope import DashscopeLLM, estimate_cost_usd
from app.llm.jev_engine import JevEngine, JevEngineUnavailable
from app.rag.ingestion import Ingestor
from app.rag.pipelines import SUFFICIENCY_THRESHOLD, ChatService
from app.rag.retriever import Embedder, VectorStore
from app.schemas import ChatRequest

logger = logging.getLogger("jevrag.bench.runner")


class RunConflictError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _trim_memory() -> None:
    """Return freed Python/glibc heap to the OS after each question.

    Long benchmark runs accumulate allocator arenas (numpy scratch, JSON blobs,
    SQLAlchemy rows); without trimming the uvicorn process grows ~25MB/question
    and eventually becomes the OOM killer's favourite victim in the 4GB sandbox.
    """
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001 — non-glibc platforms simply skip it
        pass


class BenchRunner:
    def __init__(self, settings: Settings, llm: DashscopeLLM, jev: JevEngine,
                 embedder: Embedder, store: VectorStore, ingestor: Ingestor,
                 judge: BenchJudge):
        self.settings = settings
        self.llm = llm
        self.jev = jev
        self.embedder = embedder
        self.store = store
        self.ingestor = ingestor
        self.judge = judge
        # Reuses the production ChatService's System Two helper calls (decompose,
        # query rewrite) so the bench arm executes the exact same prompts + calls.
        self.chat = ChatService(settings, llm, jev, embedder, store)
        self._task: asyncio.Task | None = None

    # ================================================================ lifecycle
    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, scenario_ids: list[str], label: str = "",
              max_questions: int | None = None) -> str:
        if self.active:
            raise RunConflictError("a benchmark run is already in progress")
        unknown = [s for s in scenario_ids if s not in SCENARIO_MAP]
        if unknown:
            raise ValueError(f"unknown scenario ids: {', '.join(unknown)}")
        if not scenario_ids:
            raise ValueError("scenario_ids must not be empty")

        # per-request cap (smoke runs) overrides the settings default; 0 = all
        limit = max_questions if max_questions else self.settings.bench_max_questions_per_scenario
        scenarios = [SCENARIO_MAP[s] for s in scenario_ids]
        total_q = sum(len(s.questions[:limit] if limit else s.questions) for s in scenarios)

        with db_session() as session:
            run = BenchRun(
                id=new_id(),
                label=label or f"bench {len(scenarios)} scenario(s)",
                status="queued",
                scenario_ids=scenario_ids,
                judge_model=self.judge.model,
                config={
                    "pipeline": "hybrid-v3",
                "orchestrator": "chat-service-shared",
                "retrieval_mode": self.settings.retrieval_mode,
                "rerank_mode": self.settings.rerank_mode,
                "reranker": (self.settings.reranker_model
                             if self.settings.rerank_mode == "cross" else "-"),
                "gate_mode": self.settings.gate_mode,
                "gate_score_threshold": self.settings.gate_score_threshold,
                "jev_sufficiency_threshold": self.settings.jev_sufficiency_threshold,
                    "top_k_retrieve": self.settings.top_k_retrieve,
                    "top_k_use": self.settings.top_k_use,
                    "llm_default": self.settings.llm_model_default,
                    "llm_reasoning": self.settings.llm_model_reasoning,
                    "pairwise": self.settings.bench_pairwise,
                    "sufficiency_threshold": self.settings.jev_sufficiency_threshold,
                    "effort_routing": self.settings.hybrid_effort_routing,
                    "passage_battery": self.settings.hybrid_passage_battery,
                    "corrective_retry": self.settings.hybrid_corrective_retry,
                    "best_of_n": self.settings.hybrid_best_of_n,
                    "citation_verify": self.settings.hybrid_citation_verify,
                    "jev_model": "jev-style-0.8b-decision-v3",
                    "embed_model": self.settings.embed_model,
                    "question_limit_per_scenario": limit or "all",
                },
                progress_total=total_q,
                progress_done=0,
                progress_stage="queued",
            )
            session.add(run)
            session.commit()
            run_id = run.id
        self._task = asyncio.create_task(self._execute(run_id, scenarios, limit))
        return run_id

    def _patch_run(self, run_id: str, **fields) -> None:
        with db_session() as session:
            run = session.get(BenchRun, run_id)
            if run is None:
                return
            for k, v in fields.items():
                setattr(run, k, v)
            session.commit()

    def _run_status(self, run_id: str) -> str | None:
        with db_session() as session:
            run = session.get(BenchRun, run_id)
            return run.status if run else None

    # ================================================================ execution
    async def _execute(self, run_id: str, scenarios: list[BenchScenario],
                       question_limit: int = 0) -> None:
        t_start = time.perf_counter()
        try:
            self._patch_run(run_id, status="running", started_at=_now(),
                            progress_stage="judge self-test")
            self._patch_run(run_id, judge_selftest=await asyncio.to_thread(self.judge.self_test))

            limit = question_limit or self.settings.bench_max_questions_per_scenario
            done = 0
            for scenario in scenarios:
                if await self._cancelled(run_id):
                    return
                self._patch_run(run_id, progress_stage=f"ingesting scenario '{scenario.id}'")
                doc_ids = await asyncio.to_thread(self._reset_scenario, scenario)

                questions = scenario.questions[:limit] if limit else scenario.questions
                for q in questions:
                    if await self._cancelled(run_id):
                        return
                    self._patch_run(run_id, progress_stage=f"[{scenario.id}] question {q.id}")
                    try:
                        await self._run_question(run_id, scenario, q, doc_ids)
                    except JevEngineUnavailable as e:
                        # fail fast: local decision engine is down — the hybrid arm
                        # is meaningless; abort instead of filling the run with errors
                        raise RuntimeError(
                            f"local Jev engine unavailable — run aborted at "
                            f"{scenario.id}/{q.id}: {e}") from e
                    except Exception as e:  # noqa: BLE001 — per-question isolation
                        logger.exception("bench question %s/%s failed", scenario.id, q.id)
                        self._persist_error(run_id, scenario, q, e)
                    done += 1
                    self._patch_run(run_id, progress_done=done)
                    _trim_memory()

            self._patch_run(run_id, progress_stage="aggregating")
            summary = await asyncio.to_thread(self._summarize, run_id)
            self._patch_run(run_id, status="completed", finished_at=_now(),
                            summary=summary, progress_stage="completed")
            logger.info("bench run %s completed in %.0fs", run_id, time.perf_counter() - t_start)
        except asyncio.CancelledError:
            self._patch_run(run_id, status="cancelled", finished_at=_now())
            raise
        except Exception as e:  # noqa: BLE001 — fatal run failure must be visible
            logger.exception("bench run %s failed", run_id)
            self._patch_run(run_id, status="failed", finished_at=_now(),
                            error=f"{type(e).__name__}: {e}", progress_stage="failed")

    async def _cancelled(self, run_id: str) -> bool:
        return await asyncio.to_thread(self._run_status, run_id) == "cancelling"

    # ================================================================ per question
    async def _run_question(self, run_id: str, scenario: BenchScenario,
                            q: BenchQuestion, doc_ids: list[str]) -> None:
        trad = await self._run_arm("traditional", q, doc_ids)

        # The jev-score subprocess can be OOM-killed transiently (sandbox memory
        # pressure); the engine auto-reloads its subprocess, so retry the hybrid
        # arm once after a grace period before declaring the engine unavailable.
        hyb = None
        last_err: JevEngineUnavailable | None = None
        for attempt in (1, 2):
            try:
                hyb = await self._run_arm("hybrid", q, doc_ids)
                break
            except JevEngineUnavailable as e:
                last_err = e
                if attempt == 1:
                    logger.warning("hybrid arm unavailable (%s) — retrying in 20s", e)
                    self._patch_run(run_id, progress_stage=f"[{scenario.id}] {q.id} jev retry after engine kill")
                    await asyncio.sleep(20)
        if hyb is None:
            # fail fast: without the local decision engine the hybrid arm is
            # meaningless — abort instead of burning the run as per-question errors
            raise JevEngineUnavailable(
                f"hybrid arm failed at {scenario.id}/{q.id}: {last_err}") from last_err

        self._patch_run(run_id, progress_stage=f"[{scenario.id}] judging {q.id}")
        t_j = time.perf_counter()
        trad_gen = await asyncio.to_thread(
            self.judge.absolute, q.question, q.reference, trad["context"], trad["answer"])
        hyb_gen = await asyncio.to_thread(
            self.judge.absolute, q.question, q.reference, hyb["context"], hyb["answer"])
        judge_ms = round((time.perf_counter() - t_j) * 1000, 1)

        pairwise: dict | None = None
        if self.settings.bench_pairwise:
            pairwise = await asyncio.to_thread(
                self.judge.pairwise, q.question, q.reference,
                {"context": trad["context"], "answer": trad["answer"]},
                {"context": hyb["context"], "answer": hyb["answer"]},
            )

        gold = list(q.gold_files)
        trad_metrics = retrieval_metrics(trad["files"], gold) if gold else {}
        hyb_metrics = retrieval_metrics(hyb["files"], gold) if gold else {}
        naive_metrics = retrieval_metrics(hyb["pre_files"][: self.settings.top_k_use], gold) if gold else {}

        rows = []
        for mode, arm, gen, metrics in (
            ("traditional", trad, trad_gen, trad_metrics),
            ("hybrid", hyb, hyb_gen, hyb_metrics),
        ):
            usage = arm["usage"]
            rows.append(BenchResult(
                id=new_id(), run_id=run_id, scenario_id=scenario.id, question_id=q.id,
                question=q.question, mode=mode, qtype=q.qtype, answerable=q.answerable,
                reference=q.reference, answer=arm["answer"], model=arm["model"],
                retrieved_files=arm["files"], pre_rerank_files=(arm.get("pre_files") if mode == "hybrid" else None),
                retrieval=metrics, naive_retrieval=(naive_metrics if mode == "hybrid" else None),
                generation=gen, pairwise=pairwise,
                timings={**arm["timings"], "judge_ms": judge_ms},
                tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
                cost_usd=estimate_cost_usd(arm["model"], usage.get("prompt_tokens", 0),
                                           usage.get("completion_tokens", 0)),
                sufficiency_p=arm.get("sufficiency_p"), verification_p=arm.get("verification_p"),
                routed_model=(arm.get("model") if mode == "hybrid" else None),
                jev_decisions=arm.get("decisions"),
            ))
        with db_session() as session:
            for r in rows:
                session.add(r)
            session.commit()

    def _persist_error(self, run_id: str, scenario: BenchScenario, q: BenchQuestion, exc: Exception) -> None:
        with db_session() as session:
            for mode in ("traditional", "hybrid"):
                session.add(BenchResult(
                    id=new_id(), run_id=run_id, scenario_id=scenario.id, question_id=q.id,
                    question=q.question, mode=mode, qtype=q.qtype, answerable=q.answerable,
                    reference=q.reference, answer="", model="",
                    error=f"{type(exc).__name__}: {exc}",
                ))
            session.commit()

    # ================================================================ scenario reset
    def _reset_scenario(self, scenario: BenchScenario) -> list[str]:
        """Delete any previous copies of this scenario's docs, re-ingest fresh."""
        from app.db import Document
        doc_ids: list[str] = []
        with db_session() as session:
            for filename in scenario.docs:
                existing = session.execute(
                    select(Document).where(Document.filename == filename)).scalars().all()
                for doc in existing:
                    self.ingestor.delete_document(session, doc.id)
            session.commit()
            for filename in scenario.docs:
                path = doc_path(scenario.id, filename)
                doc = self.ingestor.ingest_file(session, path, filename=filename,
                                                file_size=path.stat().st_size)
                if doc.status != "ready":
                    raise RuntimeError(f"ingestion failed for {filename}: {doc.error}")
                doc_ids.append(doc.id)
            session.commit()
        logger.info("scenario '%s' ingested: %d docs", scenario.id, len(doc_ids))
        return doc_ids

    # ================================================================ pipeline arms
    async def _run_arm(self, mode: str, q: BenchQuestion, doc_ids: list[str]) -> dict:
        """Drive ONE arm through the production ChatService orchestrator.

        Bench mode (ChatRequest.bench=True): no conversation rows, no persistence,
        real exceptions propagate (the JevEngineUnavailable retry logic in
        _run_question depends on it), and the done event carries the exact
        context block used for generation.

        Captured per arm (same fields the pre-v3 hand-mirrored arms produced):
        - answer / model / usage / timings / decisions / sufficiency_p /
          verification_p  <- from the `done` event
        - files       <- last `sources` event (post-screening kept passages:
                         exactly what the generator was shown as context)
        - pre_files   <- last `retrieval` event (pre-rerank candidate pool;
                         the corrective retry re-emits it, last wins, matching
                         the old mirror's behaviour)
        - context     <- done event context_used (what the judge sees)
        """
        req = ChatRequest(message=q.question, mode=mode, doc_ids=doc_ids, bench=True)
        pre_files: list[str] = []
        files: list[str] = []
        final: dict = {}
        async for evt in self.chat.run(req):
            evt_type = evt.get("type")
            if evt_type == "retrieval":
                pre_files = [c["filename"] for c in evt.get("retrieved", [])]
            elif evt_type == "sources":
                files = [c["filename"] for c in evt.get("citations", [])]
            elif evt_type == "done":
                final = evt
        timings = dict(final.get("timings") or {})
        timings["latency_ms"] = final.get("latency_ms", 0.0)
        return {
            "answer": final.get("content", ""),
            "model": final.get("model", ""),
            "usage": final.get("usage") or {},
            "context": final.get("context_used", ""),
            "files": files,
            "pre_files": pre_files,
            "timings": timings,
            "decisions": final.get("decisions") or [],
            "sufficiency_p": final.get("context_sufficiency"),
            "verification_p": final.get("verification"),
        }

    # ================================================================ aggregation
    def _summarize(self, run_id: str) -> dict:
        with db_session() as session:
            rows = session.execute(
                select(BenchResult).where(BenchResult.run_id == run_id)
                .order_by(BenchResult.scenario_id, BenchResult.question_id, BenchResult.mode)
            ).scalars().all()
            run = session.get(BenchRun, run_id)

        def _arm(rs: list[BenchResult]) -> dict:
            corr = [r.generation["correctness"] for r in rs
                    if r.generation and r.generation.get("correctness") is not None]
            faith = [r.generation["faithfulness"] for r in rs
                     if r.generation and r.generation.get("faithfulness") is not None]
            retr = [r.retrieval for r in rs if r.retrieval]
            lat = [r.timings.get("latency_ms", 0.0) for r in rs if r.timings]
            abst: dict[str, int] = defaultdict(int)
            for r in rs:
                if r.generation:
                    abst[r.generation.get("abstention", "error")] += 1
            out: dict[str, Any] = {
                "n": len(rs),
                "correctness": round(mean(corr), 4) if corr else None,
                "faithfulness": round(mean(faith), 4) if faith else None,
                "abstention": dict(abst),
                "retrieval": agg_retrieval(retr),
                "latency_ms": {"mean": round(mean(lat), 1) if lat else None,
                               "p50": pct(lat, 50), "p95": pct(lat, 95)},
                "tokens_in": sum(r.tokens_in or 0 for r in rs),
                "tokens_out": sum(r.tokens_out or 0 for r in rs),
                "cost_usd": round(sum(r.cost_usd or 0 for r in rs), 5),
                "errors": sum(1 for r in rs if r.error),
            }
            if rs and rs[0].mode == "hybrid":
                sufs = [r.sufficiency_p for r in rs if r.sufficiency_p is not None]
                vers = [r.verification_p for r in rs if r.verification_p is not None]
                naive = [r.naive_retrieval for r in rs if r.naive_retrieval]
                final = [r.retrieval for r in rs if r.retrieval]
                out["sufficiency_mean"] = round(mean(sufs), 4) if sufs else None
                out["verification_mean"] = round(mean(vers), 4) if vers else None
                agg_f, agg_n = agg_retrieval(final), agg_retrieval(naive)
                out["rerank_lift"] = {
                    k: round(agg_f[k] - agg_n[k], 4) for k in agg_f if k in agg_n
                } if agg_f and agg_n else {}
            return out

        def _pairwise(rs: list[BenchResult]) -> dict:
            pw = [r.pairwise for r in rs if r.pairwise]
            if not pw:
                return {}
            wins = sum(1 for p in pw if p.get("winner") == "hybrid")
            losses = sum(1 for p in pw if p.get("winner") == "traditional")
            ties = sum(1 for p in pw if p.get("winner") == "tie")
            n = len(pw)
            return {
                "n": n, "hybrid_wins": wins, "traditional_wins": losses, "ties": ties,
                "hybrid_win_rate": round((wins + 0.5 * ties) / n, 4),
                "position_consistency": round(
                    sum(1 for p in pw if p.get("position_consistent")) / n, 4),
            }

        scenarios_out: dict[str, Any] = {}
        sid_groups: dict[str, list[BenchResult]] = defaultdict(list)
        for r in rows:
            sid_groups[r.scenario_id].append(r)

        for sid, rs in sid_groups.items():
            trad = [r for r in rs if r.mode == "traditional"]
            hyb = [r for r in rs if r.mode == "hybrid"]
            scenarios_out[sid] = {
                "name": SCENARIO_MAP[sid].name if sid in SCENARIO_MAP else sid,
                "questions": len({r.question_id for r in rs}),
                "traditional": _arm(trad), "hybrid": _arm(hyb),
                "pairwise": _pairwise(hyb),
            }

        trad_all = [r for r in rows if r.mode == "traditional"]
        hyb_all = [r for r in rows if r.mode == "hybrid"]

        # abstention split by ground-truth answerability
        def _abst_split(subset: list[BenchResult]) -> dict:
            out = {}
            for ans_flag, key in ((True, "answerable"), (False, "unanswerable")):
                for mode in ("traditional", "hybrid"):
                    grp = [r for r in subset if r.answerable == ans_flag and r.mode == mode]
                    abst: dict[str, int] = defaultdict(int)
                    for r in grp:
                        if r.generation:
                            abst[r.generation.get("abstention", "error")] += 1
                    n = len(grp)
                    out[f"{key}_{mode}"] = {
                        "n": n, **dict(abst),
                        "proper_abstention_rate": (
                            round(abst.get("abstained", 0) / n, 4) if n and not ans_flag else None),
                        "over_abstention_rate": (
                            round(abst.get("abstained", 0) / n, 4) if n and ans_flag else None),
                        "fabrication_rate": (
                            round(abst.get("fabricated", 0) / n, 4) if n and not ans_flag else None),
                    }
            return out

        # sufficiency-gate accuracy/Brier vs ground-truth answerability (hybrid only).
        # Threshold semantics follow the run's gate mode: features -> top-1 rerank
        # score vs gate_score_threshold; jev -> noul vs jev_sufficiency_threshold.
        gate: dict[str, Any] = {}
        gated = [(r.sufficiency_p, r.answerable) for r in hyb_all if r.sufficiency_p is not None]
        if gated:
            cfg = (run.config if run else None) or {}
            mode = cfg.get("gate_mode", "features")
            thr = (cfg.get("gate_score_threshold", 0.5) if mode == "features"
                   else cfg.get("jev_sufficiency_threshold", SUFFICIENCY_THRESHOLD))
            correct = sum(1 for p, a in gated if (p >= thr) == a)
            gate = {"n": len(gated), "mode": mode, "threshold": thr,
                    "accuracy": round(correct / len(gated), 4),
                    "brier": brier([p for p, _ in gated], [a for _, a in gated])}

        summary = {
            "scenarios": scenarios_out,
            "overall": {
                "questions": len({(r.scenario_id, r.question_id) for r in rows}),
                "traditional": _arm(trad_all), "hybrid": _arm(hyb_all),
                "pairwise": _pairwise(hyb_all),
            },
            "abstention_analysis": _abst_split(rows),
            "gate_analysis": gate,
            "judge": {
                "model": run.judge_model if run else self.judge.model,
                "selftest_agreement": (run.judge_selftest or {}).get("agreement")
                if run else None,
            },
            "generated_at": _now().isoformat(),
        }
        return summary
