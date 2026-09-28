"""RAG pipelines: traditional (retrieve -> cloud LLM) and hybrid v2
(local Jev-style System One decisions + ONE cloud generator).

v2 hybrid (single-generator design, docs/jev-improvements-research.md §4):

    [1] effort routing        choice {no_retrieval, single_pass, multi_step} (~1.2s)
    [2] retrieval             single_pass: broad top-k | multi_step: decompose ->
                             per-sub-query retrieval -> deduped pool
    [3] rerank                calibrated relevance, one decide() call (unchanged)
    [4] screening battery     3 nouls/passage: evidence / premise conflict / injection
                             ordered thresholds -> include / conflict-block / drop
    [5] sufficiency gate      insufficient -> corrective retry: rewrite query (cloud
                             LLM) -> re-retrieve -> re-screen (cap 1 retry; CRAG)
    [6] generation            single model; multi_step or low-sufficiency -> 2
                             candidates (thinking off/on) + Jev best-of-2 selection
    [7] citation verification ONE batched call: choice per emitted [n] + groundedness
                             + answers-request nouls -> composite quality score

Event protocol (JSON dicts, serialized as SSE `data:` frames):
  meta | status | retrieval | decision | rerank | routing | sources | llm_start
  | delta | done | error | ping
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncGenerator

from sqlalchemy import select

from app.config import Settings
from app.db import Conversation, Message, db_session, new_id
from app.llm.dashscope import DashscopeLLM, estimate_cost_usd
from app.llm.jev_engine import JevEngine, JevEngineUnavailable
from app.rag.prompts import (
    DECOMPOSE_SYSTEM,
    HYBRID_CONFLICT_SUFFIX,
    HYBRID_DIRECT_SUFFIX,
    HYBRID_INSUFFICIENT_SUFFIX,
    HYBRID_SYSTEM,
    QUERY_REWRITE_SYSTEM,
    TRADITIONAL_SYSTEM,
    build_user_message,
    format_conflict_block,
    format_context,
)
from app.rag.retriever import Embedder, HybridSearch, RetrievedChunk, VectorStore
from app.schemas import ChatRequest

logger = logging.getLogger("jevrag.pipelines")

_SENTINEL = object()
SUFFICIENCY_THRESHOLD = 0.5

# Inline citation markers the generator is instructed to emit: [1], [2][3], [1, 2]
CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


# ============================================================ shared v2 policy
# Pure functions: imported by the bench runner so both arms apply IDENTICAL
# thresholds and scoring (backend/AGENTS.md bench contract).

def parse_citations(answer: str) -> list[int]:
    """Distinct citation labels the answer actually emitted, in order of first use."""
    labels: list[int] = []
    for m in CITE_RE.finditer(answer):
        for part in m.group(1).split(","):
            n = int(part.strip())
            if n not in labels:
                labels.append(n)
    return labels


def apply_battery_policy(chunks: list[dict], verdicts: dict[int, dict[str, float]],
                         settings: Settings) -> tuple[dict[int, str], dict[int, str]]:
    """Ordered threshold policy (TypeSafe classifying-RAG cookbook).

    Order matters: security first, then premise conflicts, then evidence quality.
    Relevance from the reranker acts as a rescue: a strongly relevant passage with
    weak evidence is kept (multi-hop partial evidence), a weak-evidence passage
    that is also weakly relevant is dropped (distractor).

    Returns (actions {chunk_index: include|conflict|drop}, reasons {chunk_index: why}).
    """
    actions: dict[int, str] = {}
    reasons: dict[int, str] = {}
    for c in chunks:
        v = verdicts.get(c["index"], {})
        injection = v.get("injection", 0.0)
        contradiction = v.get("contradiction", 0.0)
        evidence = v.get("evidence", 0.0)
        relevance = float(c.get("jev_score", 0.0) or 0.0)
        if injection >= settings.jev_injection_drop_threshold:
            actions[c["index"]] = "drop"
            reasons[c["index"]] = f"prompt injection {injection:.2f}"
        elif contradiction >= settings.jev_contradiction_block_threshold:
            actions[c["index"]] = "conflict"
            reasons[c["index"]] = f"premise contradiction {contradiction:.2f}"
        elif evidence < settings.jev_evidence_drop_threshold and relevance < 0.5:
            actions[c["index"]] = "drop"
            reasons[c["index"]] = f"no evidence {evidence:.2f} and weak relevance {relevance:.2f}"
        else:
            actions[c["index"]] = "include"
            reasons[c["index"]] = (f"evidence {evidence:.2f}" if evidence >= settings.jev_evidence_drop_threshold
                                   else f"relevance rescue {relevance:.2f}")
    return actions, reasons


def citation_summary(verdicts: dict[int, dict], settings: Settings
                     ) -> tuple[float | None, bool, dict[int, dict]]:
    """Aggregate citation verdicts.

    A citation counts as supported only when the choice is `supports` AND its
    confidence clears jev_citation_confidence (auto-accept, TypeSafe citation-check
    cookbook). Any `contradicts` verdict flags the answer as contradicting context.
    Returns (citations_supported fraction | None, contradicts_context, per-citation flags).
    """
    if not verdicts:
        return None, False, {}
    supported = 0
    contradicts = False
    flags: dict[int, dict] = {}
    for n, v in verdicts.items():
        verdict = v.get("verdict", "says_nothing")
        conf = float(v.get("confidence", 0.0) or 0.0)
        verified = verdict == "supports" and conf >= settings.jev_citation_confidence
        if verdict == "contradicts":
            contradicts = True
        flags[n] = {"verdict": verdict, "confidence": round(conf, 3), "verified": verified}
        supported += 1 if verified else 0
    return supported / len(verdicts), contradicts, flags


def composite_quality(addresses_request: float, citations_supported: float,
                      contradicts_context: bool) -> float:
    """TypeSafe composite-scoring pattern, their own answer-gating example:
    0.4*answers_request + 0.4*citations_supported + 0.2*(not contradicts_context)."""
    return round(
        0.4 * addresses_request
        + 0.4 * citations_supported
        + 0.2 * (0.0 if contradicts_context else 1.0),
        3,
    )


def _snippet(text: str, n: int = 240) -> str:
    t = " ".join(text.split())
    return t[:n] + ("…" if len(t) > n else "")


def _conversation_title(message: str) -> str:
    t = " ".join(message.split())
    return t[:60] + ("…" if len(t) > 60 else "")


class ChatService:
    def __init__(self, settings: Settings, llm: DashscopeLLM, jev: JevEngine,
                 embedder: Embedder, store: VectorStore):
        self.settings = settings
        self.llm = llm
        self.jev = jev
        self.embedder = embedder
        self.store = store
        # v3 retrieval: BM25 ‖ dense + RRF fusion (settings.retrieval_mode
        # switches it back to pure dense — the pre-v3 fallback arm).
        self.search = HybridSearch(settings, embedder, store)

    # ================================================================ public entry
    async def run(self, req: ChatRequest) -> AsyncGenerator[dict, None]:
        t_total = time.perf_counter()
        try:
            if req.bench:
                # Bench mode: no conversation rows, no persistence, ephemeral id.
                # The benchmark runner drives this same orchestrator directly.
                conv_id, history = new_id(), []
            else:
                conv_id, history = self._open_conversation(req)
            assistant_id = new_id()
            yield {
                "type": "meta", "conversation_id": conv_id, "mode": req.mode,
                "assistant_message_id": assistant_id,
            }
            agen = (self._run_hybrid if req.mode == "hybrid" else self._run_traditional)(
                req, conv_id, assistant_id, history)
            async for evt in agen:
                if evt.get("type") == "done":
                    evt["mode"] = req.mode
                    evt["conversation_id"] = conv_id
                    evt["latency_ms"] = round((time.perf_counter() - t_total) * 1000, 1)
                    if not req.bench:
                        self._persist_assistant(assistant_id, conv_id, evt)
                yield evt
        except JevEngineUnavailable as e:
            if req.bench:
                raise  # the bench runner retries on engine kills — it needs the exception
            logger.error("hybrid unavailable: %s", e)
            yield {"type": "error", "message": f"Local Jev-style engine unavailable: {e}. "
                    "Check /api/system/status — the hybrid pipeline requires it."}
        except Exception as e:  # noqa: BLE001 — surface any failure as an SSE error event
            if req.bench:
                raise
            logger.exception("pipeline failed")
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}

    # ================================================================ traditional
    async def _run_traditional(self, req: ChatRequest, conv_id: str, assistant_id: str,
                               history: list[dict]) -> AsyncGenerator[dict, None]:
        timings: dict[str, float] = {}
        decisions: list[dict] = []
        retrieved: list[dict] = []

        yield {"type": "status", "stage": "retrieving",
               "detail": f"embedding similarity search (top {self.settings.top_k_use})"}
        retrieved, timings["retrieval_ms"] = await asyncio.to_thread(
            self._retrieve, req.message, self.settings.top_k_use, req.doc_ids)
        yield {"type": "retrieval", "retrieved": self._lite(retrieved)}

        labeled = self._label(retrieved)
        citations = self._citations(labeled)
        context_block = format_context(labeled) if labeled else "(no passages retrieved)"
        yield {"type": "sources", "citations": citations}

        model = self.settings.llm_model_default
        yield {"type": "llm_start", "model": model, "system": "traditional"}
        usage: dict = {}
        async for evt in self._stream_llm(model, TRADITIONAL_SYSTEM,
                                          build_user_message(req.message, context_block), history):
            if evt["type"] == "delta":
                yield evt
            elif evt["type"] == "usage":
                usage = evt["usage"]
        timings["llm_ms"] = usage.get("_llm_ms", 0.0)
        content = usage.get("_content", "")

        yield self._done_event(assistant_id, model, content, usage, timings, decisions,
                               self._lite(retrieved), citations, "traditional",
                               extra=self._ctx(req, context_block) or None)

    # ================================================================ hybrid v2
    async def _run_hybrid(self, req: ChatRequest, conv_id: str, assistant_id: str,
                          history: list[dict]) -> AsyncGenerator[dict, None]:
        s = self.settings
        timings: dict[str, float] = {}
        decisions: list[dict] = []
        query = req.message
        model = s.llm_model_default  # single generator: no model routing in v2
        extra: dict[str, Any] = {"effort": "single_pass"}

        # -- [1] effort routing (replaces v1 model routing; ~1.2s) --------------
        kb_empty = await asyncio.to_thread(self.store.count) == 0
        effort, eprobs, econf = "single_pass", {}, 0.0
        if not kb_empty and s.hybrid_effort_routing:
            yield {"type": "status", "stage": "jev-routing",
                   "detail": "local Jev-style engine choosing retrieval effort "
                             "(no_retrieval / single_pass / multi_step)"}
            effort, eprobs, econf, rec = await asyncio.to_thread(self.jev.effort_routing, query)
            decisions.append(rec)
            timings["effort_ms"] = rec["latency_ms"]
            yield {"type": "decision", "decision": rec}
            extra["effort"] = effort
            extra["routing_probabilities"] = {k: round(v, 3) for k, v in eprobs.items()}

            if (effort == "no_retrieval"
                    and eprobs.get("no_retrieval", 0.0) >= s.jev_no_retrieval_threshold):
                # Adaptive-RAG class A: skip retrieval entirely (validated fast path —
                # P(no_retrieval) separates chat 0.76-0.96 from doc questions <=0.17).
                yield {"type": "routing", "effort": "no_retrieval", "model": model,
                       "probabilities": {k: round(v, 3) for k, v in eprobs.items()},
                       "confidence": round(econf, 3)}
                yield {"type": "sources", "citations": []}
                yield {"type": "llm_start", "model": model, "system": "hybrid",
                       "context_sufficiency": None, "direct": True}
                usage: dict = {}
                async for evt in self._stream_llm(
                        model, HYBRID_SYSTEM + HYBRID_DIRECT_SUFFIX,
                        build_user_message(query, "(no passages — question classified as "
                                        "not requiring the knowledge base)"), history):
                    if evt["type"] == "delta":
                        yield evt
                    elif evt["type"] == "usage":
                        usage = evt["usage"]
                timings["llm_ms"] = usage.get("_llm_ms", 0.0)
                yield self._done_event(assistant_id, model, usage.get("_content", ""), usage,
                                       timings, decisions, [], [], "hybrid", None, None,
                                       extra=self._ctx(req, "(no passages — question "
                                         "classified as not requiring the knowledge base)",
                                         {**extra, "effort": "no_retrieval"}))
                return
        yield {"type": "routing", "effort": effort, "model": model,
               "probabilities": {k: round(v, 3) for k, v in eprobs.items()},
               "confidence": round(econf, 3)}

        # -- [2] retrieval: broad, or decomposed for multi_step ------------------
        retrieved: list[dict] = []
        sub_queries: list[str] = []
        if effort == "multi_step" and s.hybrid_multistep and not kb_empty:
            yield {"type": "status", "stage": "retrieving",
                   "detail": "decomposing the question into sub-queries (System Two)"}
            sub_queries, decomp_usage, decomp_ms = await asyncio.to_thread(self._decompose, query)
            timings["decompose_ms"] = decomp_ms
            if len(sub_queries) > 1:
                decisions.append({
                    "name": "decompose", "label": "Question decomposition (System Two)",
                    "kind": "plan", "question": "Decompose into 2-4 standalone sub-questions",
                    "answer": sub_queries, "probabilities": None, "confidence": None,
                    "latency_ms": decomp_ms, "usage": decomp_usage or None,
                })
                yield {"type": "decision", "decision": decisions[-1]}
        if sub_queries:
            yield {"type": "status", "stage": "retrieving",
                   "detail": f"retrieving per sub-query ({len(sub_queries)} queries, "
                             f"top {s.jev_multistep_subquery_k} each)"}
            retrieved, timings["retrieval_ms"] = await asyncio.to_thread(
                self._retrieve_multi, sub_queries, req.doc_ids)
        elif not kb_empty:
            yield {"type": "status", "stage": "retrieving",
                   "detail": f"broad embedding search (top {s.top_k_retrieve})"}
            retrieved, timings["retrieval_ms"] = await asyncio.to_thread(
                self._retrieve, query, s.top_k_retrieve, req.doc_ids)
        yield {"type": "retrieval", "retrieved": self._lite(retrieved)}

        if not retrieved:
            # nothing indexed (or nothing found): answer honestly with no context
            yield {"type": "sources", "citations": []}
            yield {"type": "llm_start", "model": model, "system": "hybrid"}
            usage = {}
            async for evt in self._stream_llm(model, HYBRID_SYSTEM,
                                              build_user_message(query, "(no passages retrieved)"), history):
                if evt["type"] == "delta":
                    yield evt
                elif evt["type"] == "usage":
                    usage = evt["usage"]
            content = usage.get("_content", "")
            yield self._done_event(assistant_id, model, content, usage, timings, decisions,
                                   [], [], "hybrid", None, None,
                                   extra=self._ctx(req, "(no passages retrieved)", extra))
            return

        # -- [3-5] rerank -> battery -> gate, with one corrective retry ----------
        search_query = query
        rewritten_query: str | None = None
        max_attempts = 2 if s.hybrid_corrective_retry else 1
        screen: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            if attempt == 1:
                # CRAG corrective loop (capped at 1): rewrite -> re-retrieve -> re-screen
                yield {"type": "status", "stage": "jev-gating",
                       "detail": "context insufficient — rewriting the query and retrying retrieval"}
                rewritten_query, rw_usage, rw_ms = await asyncio.to_thread(self._rewrite_query, query)
                timings["rewrite_ms"] = rw_ms
                decisions.append({
                    "name": "corrective", "label": "Corrective query rewrite (System Two)",
                    "kind": "rewrite",
                    "question": "Rewrite the question to improve retrieval (one retry)",
                    "answer": rewritten_query, "probabilities": None, "confidence": None,
                    "latency_ms": rw_ms, "usage": rw_usage or None,
                })
                yield {"type": "decision", "decision": decisions[-1]}
                search_query = rewritten_query
                retrieved, timings["retrieval_ms"] = await asyncio.to_thread(
                    self._retrieve, search_query, s.top_k_retrieve, req.doc_ids)
                yield {"type": "retrieval", "retrieved": self._lite(retrieved)}
                if not retrieved:
                    screen = None
                    break

            ranked, rerank_rec = await asyncio.to_thread(
                self.jev.rerank_chunks, search_query, retrieved, s.jev_rerank_char_limit)
            decisions.append(rerank_rec)
            timings["rerank_ms"] = rerank_rec["latency_ms"]
            yield {"type": "decision", "decision": rerank_rec}

            kept = ranked[: s.top_k_use]
            yield {"type": "rerank", "kept": self._lite(kept)}

            include, conflict = kept, []
            if s.hybrid_passage_battery and kept:
                yield {"type": "status", "stage": "jev-screening",
                       "detail": "screening passages: answer evidence · premise conflicts · prompt injection"}
                verdicts, bat_rec = await asyncio.to_thread(
                    self.jev.screen_passages, search_query, kept, s.jev_rerank_char_limit)
                actions, reasons = apply_battery_policy(kept, verdicts, s)
                bat_rec["answer"] = {f"passage {i}": f"{actions[i]} — {reasons[i]}"
                                     for i in sorted(actions)}
                decisions.append(bat_rec)
                timings["battery_ms"] = bat_rec["latency_ms"]
                yield {"type": "decision", "decision": bat_rec}
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

            suf_p, suf_rec = await asyncio.to_thread(self.jev.sufficiency, query, ctx_for_jev)
            decisions.append(suf_rec)
            timings["sufficiency_ms"] = suf_rec["latency_ms"]
            yield {"type": "decision", "decision": suf_rec}

            screen = {"labeled": labeled, "main": main, "flagged": flagged,
                      "context_block": context_block, "ctx_for_jev": ctx_for_jev,
                      "suf_p": suf_p, "kept": kept}
            if suf_p >= SUFFICIENCY_THRESHOLD:
                break  # sufficient — stop screening

        # screen is None only when the corrective retry's re-retrieval found nothing
        if screen is None:
            # corrective retry also found nothing: fall through to the honest no-context answer
            yield {"type": "sources", "citations": []}
            yield {"type": "llm_start", "model": model, "system": "hybrid"}
            usage = {}
            async for evt in self._stream_llm(model, HYBRID_SYSTEM + HYBRID_INSUFFICIENT_SUFFIX,
                                              build_user_message(query, "(no passages retrieved)"), history):
                if evt["type"] == "delta":
                    yield evt
                elif evt["type"] == "usage":
                    usage = evt["usage"]
            content = usage.get("_content", "")
            extra["retried"] = True
            extra["rewritten_query"] = rewritten_query
            yield self._done_event(assistant_id, model, content, usage, timings, decisions,
                                   self._lite(retrieved), [], "hybrid", None, None,
                                   extra=self._ctx(req, "(no passages retrieved)", extra))
            return

        labeled = screen["labeled"]
        context_block = screen["context_block"]
        ctx_for_jev = screen["ctx_for_jev"]
        suf_p = screen["suf_p"]
        citations = self._citations(labeled)
        yield {"type": "sources", "citations": citations}
        extra.update({"retried": rewritten_query is not None,
                      "rewritten_query": rewritten_query,
                      "conflict_passages": len(screen["flagged"])})

        # -- [6] generation: single model; best-of-2 on the hard path ------------
        system = HYBRID_SYSTEM
        if suf_p < SUFFICIENCY_THRESHOLD:
            system += HYBRID_INSUFFICIENT_SUFFIX
        if screen["flagged"]:
            system += HYBRID_CONFLICT_SUFFIX
        user_msg = build_user_message(query, context_block)

        best_of = s.hybrid_best_of_n and (effort == "multi_step" or suf_p < SUFFICIENCY_THRESHOLD)
        usage: dict = {}
        content = ""
        if best_of:
            # Speculative-RAG-style sampling: two candidates from the SAME generator
            # (thinking off / thinking on), generated concurrently, then ONE Jev call
            # picks the winner by calibrated P(grounded) — a relative selector.
            yield {"type": "status", "stage": "answering",
                   "detail": "sampling 2 candidates (direct + reasoned) — Jev will select"}
            yield {"type": "llm_start", "model": model, "system": "hybrid",
                   "context_sufficiency": round(suf_p, 3), "best_of": 2}
            t0 = time.perf_counter()
            (cand_direct, u_direct), (cand_reasoned, u_reasoned) = await asyncio.gather(
                asyncio.to_thread(self.llm.complete, model=model, system=system,
                                  user=user_msg, enable_thinking=False),
                asyncio.to_thread(self.llm.complete, model=model, system=system,
                                  user=user_msg, enable_thinking=True),
            )
            timings["llm_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            winner, scores, rec = await asyncio.to_thread(
                self.jev.select_best_candidate, query, ctx_for_jev,
                {"direct": cand_direct, "reasoned": cand_reasoned})
            decisions.append(rec)
            timings["select_ms"] = rec["latency_ms"]
            yield {"type": "decision", "decision": rec}
            content = cand_direct if winner != "reasoned" else cand_reasoned
            usage = {
                "prompt_tokens": (u_direct.get("prompt_tokens", 0)
                                  + u_reasoned.get("prompt_tokens", 0)),
                "completion_tokens": (u_direct.get("completion_tokens", 0)
                                      + u_reasoned.get("completion_tokens", 0)),
            }
            extra["best_of"] = {k: round(v, 3) for k, v in scores.items()}
            # emit the winner progressively (paragraph chunks keep the typing feel)
            parts = content.split("\n\n")
            for i, part in enumerate(parts):
                yield {"type": "delta", "content": part + ("\n\n" if i < len(parts) - 1 else "")}
        else:
            yield {"type": "llm_start", "model": model, "system": "hybrid",
                   "context_sufficiency": round(suf_p, 3)}
            async for evt in self._stream_llm(model, system, user_msg, history):
                if evt["type"] == "delta":
                    yield evt
                elif evt["type"] == "usage":
                    usage = evt["usage"]
            timings["llm_ms"] = usage.get("_llm_ms", 0.0)
            content = usage.get("_content", "")

        # -- [7] citation-level verification + composite quality (ONE call) -----
        verification: float | None = None
        quality: float | None = None
        citation_flags: dict[int, dict] | None = None
        if s.hybrid_verify_answers and content.strip():
            if s.hybrid_citation_verify and labeled:
                cited = parse_citations(content)
                yield {"type": "status", "stage": "jev-verifying",
                       "detail": f"verifying {len(cited)} citation(s): supports / contradicts / says_nothing"}
                try:
                    verdicts, grounded_p, addresses_p, recs = await asyncio.to_thread(
                        self.jev.verify_citations_and_quality, query, content[:4000],
                        ctx_for_jev, labeled, cited, s.jev_context_char_limit)
                    for rec in recs:
                        decisions.append(rec)
                        yield {"type": "decision", "decision": rec}
                    if recs:
                        timings["citations_ms"] = recs[0]["latency_ms"]
                    verification = round(grounded_p, 3) if grounded_p is not None else None
                    cites_supported, contradicts, citation_flags = citation_summary(verdicts, s)
                    if addresses_p is not None and cites_supported is not None:
                        quality = composite_quality(addresses_p, cites_supported, contradicts)
                        decisions.append({
                            "name": "composite", "label": "Composite answer quality",
                            "kind": "noul",
                            "question": "0.4 · answers_request + 0.4 · citations_supported "
                                        "+ 0.2 · (not contradicts_context)",
                            "answer": quality,
                            "probabilities": {
                                "answers_request": round(addresses_p, 3),
                                "citations_supported": round(cites_supported, 3),
                                "no_contradiction": 0.0 if contradicts else 1.0,
                            },
                            "confidence": None, "latency_ms": 0.0, "usage": None,
                        })
                        yield {"type": "decision", "decision": decisions[-1]}
                    extra["quality_score"] = quality
                    extra["citations_verified"] = (
                        {str(k): v for k, v in citation_flags.items()} if citation_flags else {})
                except Exception as e:  # noqa: BLE001 — verification is best-effort
                    logger.warning("citation verification failed (non-fatal): %s", e)
            else:
                yield {"type": "status", "stage": "jev-verifying",
                       "detail": "local Jev-style engine checking answer groundedness"}
                try:
                    p, ver_rec = await asyncio.to_thread(
                        self.jev.verify_groundedness, query, content[:4000], ctx_for_jev)
                    decisions.append(ver_rec)
                    verification = round(p, 3)
                    yield {"type": "decision", "decision": ver_rec}
                except Exception as e:  # noqa: BLE001 — verification is best-effort
                    logger.warning("verification failed (non-fatal): %s", e)

        yield self._done_event(assistant_id, model, content, usage, timings, decisions,
                               self._lite(retrieved), citations, "hybrid", verification,
                               round(suf_p, 3), extra=self._ctx(req, context_block, extra))

    # ================================================================ helpers
    def _retrieve(self, query: str, k: int,
                  doc_ids: list[str] | None = None) -> tuple[list[dict], float]:
        t0 = time.perf_counter()
        chunks: list[RetrievedChunk] = self.search.retrieve(query, k, doc_ids=doc_ids)
        ms = (time.perf_counter() - t0) * 1000
        out: list[dict] = []
        for i, c in enumerate(chunks):
            d = c.as_dict()
            d["retrieval_rank"] = i + 1
            d["index"] = i + 1  # 1-based label used inside Jev rerank states
            out.append(d)
        return out, ms

    def _retrieve_multi(self, sub_queries: list[str],
                        doc_ids: list[str] | None = None) -> tuple[list[dict], float]:
        """Multi-step retrieval: per-sub-query search, dedupe by chunk, cap the pool.

        The pool is ranked by best similarity across sub-queries before capping at
        jev_multistep_max_pool (rerank latency scales with pool size on CPU).
        """
        t0 = time.perf_counter()
        seen: dict[str, dict] = {}
        for sq in sub_queries:
            for c in self.search.retrieve(sq, self.settings.jev_multistep_subquery_k,
                                          doc_ids=doc_ids):
                d = c.as_dict()
                if d["chunk_id"] not in seen:
                    seen[d["chunk_id"]] = d
        # pool order: fused RRF score in hybrid_rrf mode (covers lexical-only
        # hits), dense cosine similarity in dense mode — consistent within a mode
        pool = sorted(seen.values(),
                      key=lambda d: d["rrf_score"] if d.get("rrf_score") is not None
                      else d.get("similarity", 0.0), reverse=True)
        pool = pool[: self.settings.jev_multistep_max_pool]
        for i, d in enumerate(pool):
            d["retrieval_rank"] = i + 1
            d["index"] = i + 1
        ms = (time.perf_counter() - t0) * 1000
        return pool, ms

    def _decompose(self, query: str) -> tuple[list[str], dict, float]:
        """System Two as a tool: split a multi-step question into sub-queries."""
        t0 = time.perf_counter()
        try:
            text, usage = self.llm.complete(
                model=self.settings.llm_model_default, system=DECOMPOSE_SYSTEM,
                user=query, max_tokens=300, temperature=0.1)
        except Exception as e:  # noqa: BLE001 — decomposition failure degrades to single_pass
            logger.warning("decomposition failed (%s) — falling back to broad retrieval", e)
            return [query], {}, round((time.perf_counter() - t0) * 1000, 1)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        subs: list[str] = []
        try:
            raw = text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", raw).strip()
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                subs = [str(q).strip() for q in parsed if str(q).strip()]
        except Exception:  # noqa: BLE001 — malformed JSON degrades to single_pass
            logger.warning("decomposition output not valid JSON — falling back")
        if not subs:
            subs = [query]
        return subs[:4], usage, ms

    def _rewrite_query(self, query: str) -> tuple[str, dict, float]:
        """CRAG corrective action: rewrite the query for a better retrieval retry."""
        t0 = time.perf_counter()
        try:
            text, usage = self.llm.complete(
                model=self.settings.llm_model_default, system=QUERY_REWRITE_SYSTEM,
                user=query, max_tokens=200, temperature=0.2)
        except Exception as e:  # noqa: BLE001 — rewrite failure keeps the original query
            logger.warning("query rewrite failed (%s) — retrying with original", e)
            return query, {}, round((time.perf_counter() - t0) * 1000, 1)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        rewritten = text.strip().strip('"').splitlines()[0].strip() if text.strip() else ""
        return rewritten or query, usage, ms

    @staticmethod
    def _lite(chunks: list[dict]) -> list[dict]:
        return [
            {
                "rank": c.get("retrieval_rank"),
                "chunk_id": c["chunk_id"], "filename": c["filename"],
                "similarity": c["similarity"], "jev_score": c.get("jev_score"),
                "snippet": _snippet(c["text"]),
            }
            for c in chunks
        ]

    @staticmethod
    def _label(kept: list[dict]) -> list[dict]:
        out = []
        for i, c in enumerate(kept):
            d = dict(c)
            d["chunk_index_label"] = i + 1
            out.append(d)
        return out

    @staticmethod
    def _citations(labeled: list[dict]) -> list[dict]:
        return [
            {
                "index": d["chunk_index_label"], "chunk_id": d["chunk_id"], "doc_id": d["doc_id"],
                "filename": d["filename"], "similarity": d["similarity"],
                "rerank_score": d.get("jev_score"), "snippet": _snippet(d["text"]),
            }
            for d in labeled
        ]

    async def _stream_llm(self, model: str, system: str, user: str,
                          history: list[dict]) -> AsyncGenerator[dict, None]:
        """Bridges the sync OpenAI stream into async events (thread pool)."""
        it = self.llm.stream_answer(model=model, system=system, user=user, history=history)
        t0 = time.perf_counter()
        parts: list[str] = []
        usage: dict = {}
        while True:
            evt = await asyncio.to_thread(next, it, _SENTINEL)
            if evt is _SENTINEL:
                break
            if evt.type == "delta":
                parts.append(evt.content)
                yield {"type": "delta", "content": evt.content}
            elif evt.type == "usage":
                usage = dict(evt.usage)
        usage["_llm_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        usage["_content"] = "".join(parts)
        yield {"type": "usage", "usage": usage}

    # ================================================================ persistence
    def _open_conversation(self, req: ChatRequest) -> tuple[str, list[dict]]:
        with db_session() as session:
            conv = None
            if req.conversation_id:
                conv = session.get(Conversation, req.conversation_id)
            if conv is None:
                conv = Conversation(id=req.conversation_id or new_id(),
                                    title=_conversation_title(req.message))
                session.add(conv)
                session.commit()
            user_msg = Message(conversation_id=conv.id, role="user", mode=req.mode,
                               content=req.message)
            session.add(user_msg)
            session.commit()
            rows = session.execute(
                select(Message)
                .where(Message.conversation_id == conv.id, Message.id != user_msg.id,
                       Message.content != "")
                .order_by(Message.created_at.desc())
                .limit(8)
            ).scalars().all()
            history = [{"role": m.role, "content": m.content} for m in reversed(rows)]
            return conv.id, history

    def _persist_assistant(self, message_id: str, conv_id: str, final: dict) -> None:
        try:
            with db_session() as session:
                msg = Message(
                    id=message_id, conversation_id=conv_id, role="assistant", mode=final.get("mode"),
                    content=final.get("content", ""), model=final.get("model"),
                    latency_ms=final.get("latency_ms"),
                    prompt_tokens=(final.get("usage") or {}).get("prompt_tokens"),
                    completion_tokens=(final.get("usage") or {}).get("completion_tokens"),
                    cost_usd=final.get("cost_usd"),
                    trace={
                        "pipeline": final.get("pipeline"),
                        "timings": final.get("timings"),
                        "decisions": final.get("decisions"),
                        "retrieved": final.get("retrieved"),
                        "citations": final.get("citations"),
                        "context_sufficiency": final.get("context_sufficiency"),
                        "verification": final.get("verification"),
                        "routing_probabilities": final.get("routing_probabilities"),
                        "effort": final.get("effort"),
                        "quality_score": final.get("quality_score"),
                        "best_of": final.get("best_of"),
                        "retried": final.get("retried"),
                        "rewritten_query": final.get("rewritten_query"),
                        "citations_verified": final.get("citations_verified"),
                    },
                )
                session.add(msg)
                session.commit()
        except Exception as e:  # noqa: BLE001 — persistence must not kill the stream
            logger.error("failed to persist assistant message: %s", e)

    @staticmethod
    def _ctx(req: ChatRequest, context_block: str, extra: dict | None = None) -> dict:
        """Merge the bench-only context_used field into a done-event extra dict."""
        out = dict(extra or {})
        if req.bench:
            out["context_used"] = context_block
        return out

    def _done_event(self, assistant_id: str, model: str, content: str, usage: dict,
                    timings: dict, decisions: list, retrieved: list, citations: list,
                    pipeline: str, verification: float | None = None,
                    sufficiency: float | None = None, extra: dict | None = None) -> dict:
        out = {
            "type": "done", "message_id": assistant_id, "model": model, "content": content,
            "usage": {k: v for k, v in usage.items() if not k.startswith("_")},
            "cost_usd": estimate_cost_usd(model, usage.get("prompt_tokens", 0),
                                          usage.get("completion_tokens", 0)),
            "timings": timings, "decisions": decisions, "retrieved": retrieved,
            "citations": citations, "pipeline": pipeline,
            "verification": verification, "context_sufficiency": sufficiency,
        }
        if extra:
            out.update(extra)
        return out
