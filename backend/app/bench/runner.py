"""Benchmark orchestration: ingest scenario -> run BOTH pipelines -> judge -> aggregate.

Fairness protocol (docs/benchmarking.md):
- Both arms answer the SAME questions over the SAME corpus snapshot with the SAME
  prompts, chunking, embeddings and knobs as the production pipelines.
- Matched final context budget: traditional retrieves top_k_use=4 directly;
  hybrid retrieves top_k_retrieve=10, Jev-reranks, keeps top_k_use=4.
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
from app.rag.pipelines import (
    SUFFICIENCY_THRESHOLD,
    ChatService,
    apply_battery_policy,
    citation_summary,
    composite_quality,
    parse_citations,
)
from app.rag.prompts import (
    HYBRID_CONFLICT_SUFFIX,
    HYBRID_DIRECT_SUFFIX,
    HYBRID_INSUFFICIENT_SUFFIX,
    HYBRID_SYSTEM,
    TRADITIONAL_SYSTEM,
    build_user_message,
    format_conflict_block,
    format_context,
)
from app.rag.retriever import Embedder, VectorStore

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
                    "pipeline": "hybrid-v2",
                    "top_k_retrieve": self.settings.top_k_retrieve,
                    "top_k_use": self.settings.top_k_use,
                    "llm_default": self.settings.llm_model_default,
                    "llm_reasoning": self.settings.llm_model_reasoning,
                    "pairwise": self.settings.bench_pairwise,
                    "sufficiency_threshold": SUFFICIENCY_THRESHOLD,
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
        trad = await self._arm_traditional(q, doc_ids)

        # The jev-score subprocess can be OOM-killed transiently (sandbox memory
        # pressure); the engine auto-reloads its subprocess, so retry the hybrid
        # arm once after a grace period before declaring the engine unavailable.
        hyb = None
        last_err: JevEngineUnavailable | None = None
        for attempt in (1, 2):
            try:
                hyb = await self._arm_hybrid(q, doc_ids)
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
    def _retrieve_sync(self, query: str, k: int, doc_ids: list[str] | None) -> tuple[list[dict], float]:
        t0 = time.perf_counter()
        embedding = self.embedder.embed_query(query)
        chunks = self.store.query(embedding, k, doc_ids=doc_ids)
        ms = (time.perf_counter() - t0) * 1000
        out: list[dict] = []
        for i, c in enumerate(chunks):
            d = c.as_dict()
            d["retrieval_rank"] = i + 1
            d["index"] = i + 1
            out.append(d)
        return out, ms

    def _complete_sync(self, model: str, system: str, user: str) -> tuple[str, dict]:
        t0 = time.perf_counter()
        parts: list[str] = []
        usage: dict = {}
        for evt in self.llm.stream_answer(model=model, system=system, user=user):
            if evt.type == "delta":
                parts.append(evt.content)
            elif evt.type == "usage":
                usage = dict(evt.usage)
        usage["_llm_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return "".join(parts), usage

    @staticmethod
    def _label(chunks: list[dict]) -> list[dict]:
        return [{**c, "chunk_index_label": i + 1} for i, c in enumerate(chunks)]

    async def _arm_traditional(self, q: BenchQuestion, doc_ids: list[str]) -> dict:
        """Mirror of pipelines._run_traditional (matched top_k_use context budget)."""
        t0 = time.perf_counter()
        retrieved, retrieval_ms = await asyncio.to_thread(
            self._retrieve_sync, q.question, self.settings.top_k_use, doc_ids)

        labeled = self._label(retrieved)
        context_block = format_context(labeled) if labeled else "(no passages retrieved)"
        model = self.settings.llm_model_default
        answer, usage = await asyncio.to_thread(
            self._complete_sync, model, TRADITIONAL_SYSTEM,
            build_user_message(q.question, context_block))

        return {
            "answer": answer, "model": model, "usage": usage, "context": context_block,
            "files": [c["filename"] for c in retrieved], "chunks": retrieved,
            "timings": {"retrieval_ms": round(retrieval_ms, 1),
                        "llm_ms": usage.get("_llm_ms", 0.0),
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 1)},
        }

    async def _arm_hybrid(self, q: BenchQuestion, doc_ids: list[str]) -> dict:
        """Mirror of pipelines._run_hybrid v2 (single-generator design):

        effort routing -> retrieval (broad / decomposed) -> Jev rerank -> screening
        battery -> sufficiency gate (+ corrective retry) -> generation (best-of-2 on
        the hard path) -> citation verification -> composite quality.
        Shares prompts, engine methods, policy functions and System Two helpers with
        the production pipeline; only the retrieval adds the scenario doc_ids filter.
        """
        t0 = time.perf_counter()
        s = self.settings
        timings: dict[str, float] = {}
        decisions: list[dict] = []
        model = s.llm_model_default
        extra: dict[str, Any] = {"effort": "single_pass"}

        # -- [1] effort routing ---------------------------------------------------
        effort, eprobs, econf = "single_pass", {}, 0.0
        if s.hybrid_effort_routing:
            effort, eprobs, econf, rec = await asyncio.to_thread(
                self.jev.effort_routing, q.question)
            decisions.append(rec)
            timings["effort_ms"] = rec["latency_ms"]
            if (effort == "no_retrieval"
                    and eprobs.get("no_retrieval", 0.0) >= s.jev_no_retrieval_threshold):
                answer, usage = await asyncio.to_thread(
                    self._complete_sync, model, HYBRID_SYSTEM + HYBRID_DIRECT_SUFFIX,
                    build_user_message(q.question, "(no passages — question classified as "
                                     "not requiring the knowledge base)"))
                timings["llm_ms"] = usage.get("_llm_ms", 0.0)
                timings["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                return {"answer": answer, "model": model, "usage": usage, "effort": "no_retrieval",
                        "context": "(no passages)", "files": [], "pre_files": [], "chunks": [],
                        "timings": timings, "decisions": decisions,
                        "sufficiency_p": None, "verification_p": None, "extra": extra}

        # -- [2] retrieval (broad or decomposed) -----------------------------------
        retrieved: list[dict] = []
        sub_queries: list[str] = []
        if effort == "multi_step" and s.hybrid_multistep:
            sub_queries, decomp_usage, decomp_ms = await asyncio.to_thread(
                self.chat._decompose, q.question)
            timings["decompose_ms"] = decomp_ms
            if len(sub_queries) > 1:
                decisions.append({
                    "name": "decompose", "label": "Question decomposition (System Two)",
                    "kind": "plan", "question": "Decompose into 2-4 standalone sub-questions",
                    "answer": sub_queries, "probabilities": None, "confidence": None,
                    "latency_ms": decomp_ms, "usage": decomp_usage or None,
                })
        if sub_queries:
            retrieved, retrieval_ms = await asyncio.to_thread(
                self._retrieve_multi_sync, sub_queries, doc_ids)
        else:
            retrieved, retrieval_ms = await asyncio.to_thread(
                self._retrieve_sync, q.question, s.top_k_retrieve, doc_ids)
        timings["retrieval_ms"] = round(retrieval_ms, 1)
        pre_files = [c["filename"] for c in retrieved]

        if not retrieved:
            answer, usage = await asyncio.to_thread(
                self._complete_sync, model, HYBRID_SYSTEM,
                build_user_message(q.question, "(no passages retrieved)"))
            timings["llm_ms"] = usage.get("_llm_ms", 0.0)
            timings["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return {"answer": answer, "model": model, "usage": usage, "effort": effort,
                    "context": "(no passages retrieved)", "files": [], "pre_files": [],
                    "chunks": [], "timings": timings, "decisions": decisions,
                    "sufficiency_p": None, "verification_p": None, "extra": extra}

        # -- [3-5] rerank -> battery -> gate (+ one corrective retry) ---------------
        search_query = q.question
        rewritten_query: str | None = None
        max_attempts = 2 if s.hybrid_corrective_retry else 1
        screen: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            if attempt == 1:
                rewritten_query, rw_usage, rw_ms = await asyncio.to_thread(
                    self.chat._rewrite_query, q.question)
                timings["rewrite_ms"] = rw_ms
                decisions.append({
                    "name": "corrective", "label": "Corrective query rewrite (System Two)",
                    "kind": "rewrite",
                    "question": "Rewrite the question to improve retrieval (one retry)",
                    "answer": rewritten_query, "probabilities": None, "confidence": None,
                    "latency_ms": rw_ms, "usage": rw_usage or None,
                })
                search_query = rewritten_query
                retrieved, retrieval_ms = await asyncio.to_thread(
                    self._retrieve_sync, search_query, s.top_k_retrieve, doc_ids)
                timings["retrieval_ms"] = round(retrieval_ms, 1)
                pre_files = [c["filename"] for c in retrieved]
                if not retrieved:
                    screen = None
                    break

            ranked, rerank_rec = await asyncio.to_thread(
                self.jev.rerank_chunks, search_query, retrieved, s.jev_rerank_char_limit)
            decisions.append(rerank_rec)
            timings["rerank_ms"] = rerank_rec["latency_ms"]

            kept = ranked[: s.top_k_use]
            include, conflict = kept, []
            if s.hybrid_passage_battery and kept:
                verdicts, bat_rec = await asyncio.to_thread(
                    self.jev.screen_passages, search_query, kept, s.jev_rerank_char_limit)
                actions, reasons = apply_battery_policy(kept, verdicts, s)
                bat_rec["answer"] = {f"passage {i}": f"{actions[i]} — {reasons[i]}"
                                     for i in sorted(actions)}
                decisions.append(bat_rec)
                timings["battery_ms"] = bat_rec["latency_ms"]
                include = [c for c in kept if actions[c["index"]] == "include"]
                conflict = [c for c in kept if actions[c["index"]] == "conflict"]

            labeled = self._label(include + conflict)
            main, flagged = labeled[: len(include)], labeled[len(include):]
            context_block = format_context(main) if main else "(no passages retained after screening)"
            if flagged:
                context_block += "\n\n" + format_conflict_block(flagged)
            ctx_for_jev = "\n\n".join(
                f"Passage [{d['chunk_index_label']}] (source: {d['filename']}):\n"
                f"{d['text'][: s.jev_context_char_limit]}"
                for d in labeled
            )

            suf_p, suf_rec = await asyncio.to_thread(self.jev.sufficiency, q.question, ctx_for_jev)
            decisions.append(suf_rec)
            timings["sufficiency_ms"] = suf_rec["latency_ms"]

            screen = {"labeled": labeled, "flagged": flagged, "context_block": context_block,
                      "ctx_for_jev": ctx_for_jev, "suf_p": suf_p, "kept": kept}
            if suf_p >= SUFFICIENCY_THRESHOLD:
                break

        if screen is None:
            answer, usage = await asyncio.to_thread(
                self._complete_sync, model, HYBRID_SYSTEM + HYBRID_INSUFFICIENT_SUFFIX,
                build_user_message(q.question, "(no passages retrieved)"))
            timings["llm_ms"] = usage.get("_llm_ms", 0.0)
            timings["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return {"answer": answer, "model": model, "usage": usage, "effort": effort,
                    "context": "(no passages retrieved)", "files": [], "pre_files": pre_files,
                    "chunks": [], "timings": timings, "decisions": decisions,
                    "sufficiency_p": None, "verification_p": None, "extra": extra}

        labeled = screen["labeled"]
        context_block = screen["context_block"]
        ctx_for_jev = screen["ctx_for_jev"]
        suf_p = screen["suf_p"]
        kept = screen["kept"]
        extra.update({"effort": effort, "retried": rewritten_query is not None,
                      "rewritten_query": rewritten_query,
                      "conflict_passages": len(screen["flagged"])})

        # -- [6] generation (best-of-2 on the hard path) ----------------------------
        system = HYBRID_SYSTEM
        if suf_p < SUFFICIENCY_THRESHOLD:
            system += HYBRID_INSUFFICIENT_SUFFIX
        if screen["flagged"]:
            system += HYBRID_CONFLICT_SUFFIX
        user_msg = build_user_message(q.question, context_block)

        best_of = s.hybrid_best_of_n and (effort == "multi_step" or suf_p < SUFFICIENCY_THRESHOLD)
        answer, usage = "", {}
        if best_of:
            t_gen = time.perf_counter()
            (cand_direct, u_direct), (cand_reasoned, u_reasoned) = await asyncio.gather(
                asyncio.to_thread(self.llm.complete, model=model, system=system,
                                  user=user_msg, enable_thinking=False),
                asyncio.to_thread(self.llm.complete, model=model, system=system,
                                  user=user_msg, enable_thinking=True),
            )
            winner, scores, rec = await asyncio.to_thread(
                self.jev.select_best_candidate, q.question, ctx_for_jev,
                {"direct": cand_direct, "reasoned": cand_reasoned})
            decisions.append(rec)
            timings["select_ms"] = rec["latency_ms"]
            answer = cand_direct if winner != "reasoned" else cand_reasoned
            usage = {
                "prompt_tokens": (u_direct.get("prompt_tokens", 0)
                                  + u_reasoned.get("prompt_tokens", 0)),
                "completion_tokens": (u_direct.get("completion_tokens", 0)
                                      + u_reasoned.get("completion_tokens", 0)),
                "_llm_ms": round((time.perf_counter() - t_gen) * 1000, 1),
            }
            extra["best_of"] = {k: round(v, 3) for k, v in scores.items()}
        else:
            answer, usage = await asyncio.to_thread(
                self._complete_sync, model, system, user_msg)
        timings["llm_ms"] = usage.get("_llm_ms", 0.0)

        # -- [7] citation verification + composite quality ---------------------------
        verification_p: float | None = None
        if s.hybrid_verify_answers and answer.strip():
            if s.hybrid_citation_verify and labeled:
                cited = parse_citations(answer)
                try:
                    verdicts, grounded_p, addresses_p, recs = await asyncio.to_thread(
                        self.jev.verify_citations_and_quality, q.question, answer[:4000],
                        ctx_for_jev, labeled, cited, s.jev_context_char_limit)
                    decisions.extend(recs)
                    if recs:
                        timings["citations_ms"] = recs[0]["latency_ms"]
                    verification_p = round(grounded_p, 4) if grounded_p is not None else None
                    cites_supported, contradicts, flags = citation_summary(verdicts, s)
                    if addresses_p is not None and cites_supported is not None:
                        extra["quality_score"] = composite_quality(
                            addresses_p, cites_supported, contradicts)
                        extra["citations_verified"] = {str(k): v for k, v in flags.items()} or {}
                except Exception as e:  # noqa: BLE001 — best-effort, mirrors production
                    logger.warning("bench citation verification failed (non-fatal): %s", e)
            else:
                try:
                    verification_p, ver_rec = await asyncio.to_thread(
                        self.jev.verify_groundedness, q.question, answer[:4000], ctx_for_jev)
                    decisions.append(ver_rec)
                    timings["verify_ms"] = ver_rec["latency_ms"]
                except Exception as e:  # noqa: BLE001 — best-effort, mirrors production
                    logger.warning("bench verification failed (non-fatal): %s", e)

        timings["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "answer": answer, "model": model, "usage": usage, "effort": effort,
            "context": context_block,
            "files": [c["filename"] for c in labeled], "pre_files": pre_files, "chunks": kept,
            "timings": timings, "decisions": decisions,
            "sufficiency_p": round(suf_p, 4), "verification_p": verification_p,
            "extra": extra,
        }

    def _retrieve_multi_sync(self, sub_queries: list[str], doc_ids: list[str]
                             ) -> tuple[list[dict], float]:
        """Mirror of ChatService._retrieve_multi with the scenario doc_ids filter."""
        t0 = time.perf_counter()
        seen: dict[str, dict] = {}
        for sq in sub_queries:
            embedding = self.embedder.embed_query(sq)
            for c in self.store.query(embedding, self.settings.jev_multistep_subquery_k,
                                      doc_ids=doc_ids):
                d = c.as_dict()
                if d["chunk_id"] not in seen:
                    seen[d["chunk_id"]] = d
        pool = sorted(seen.values(), key=lambda d: d.get("similarity", 0.0), reverse=True)
        pool = pool[: self.settings.jev_multistep_max_pool]
        for i, d in enumerate(pool):
            d["retrieval_rank"] = i + 1
            d["index"] = i + 1
        ms = (time.perf_counter() - t0) * 1000
        return pool, ms

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

        # sufficiency-gate accuracy/Brier vs ground-truth answerability (hybrid only)
        gate = {}
        gated = [(r.sufficiency_p, r.answerable) for r in hyb_all if r.sufficiency_p is not None]
        if gated:
            correct = sum(1 for p, a in gated if (p >= SUFFICIENCY_THRESHOLD) == a)
            gate = {"n": len(gated),
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
