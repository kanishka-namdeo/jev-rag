"""RAG pipelines: traditional (retrieve -> cloud LLM) and hybrid
(local Jev-style System One decisions + cloud LLM System Two).

Event protocol (JSON dicts, serialized as SSE `data:` frames):
  meta | status | retrieval | decision | rerank | routing | sources | llm_start
  | delta | done | error | ping
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncGenerator

from sqlalchemy import select

from app.config import Settings
from app.db import Conversation, Message, db_session, new_id
from app.llm.dashscope import DashscopeLLM, estimate_cost_usd
from app.llm.jev_engine import JevEngine, JevEngineUnavailable
from app.rag.prompts import (
    HYBRID_INSUFFICIENT_SUFFIX,
    HYBRID_SYSTEM,
    TRADITIONAL_SYSTEM,
    build_user_message,
    format_context,
)
from app.rag.retriever import Embedder, RetrievedChunk, VectorStore
from app.schemas import ChatRequest

logger = logging.getLogger("jevrag.pipelines")

_SENTINEL = object()
SUFFICIENCY_THRESHOLD = 0.5


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

    # ================================================================ public entry
    async def run(self, req: ChatRequest) -> AsyncGenerator[dict, None]:
        t_total = time.perf_counter()
        try:
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
                    self._persist_assistant(assistant_id, conv_id, evt)
                yield evt
        except JevEngineUnavailable as e:
            logger.error("hybrid unavailable: %s", e)
            yield {"type": "error", "message": f"Local Jev-style engine unavailable: {e}. "
                    "Check /api/system/status — the hybrid pipeline requires it."}
        except Exception as e:  # noqa: BLE001 — surface any failure as an SSE error event
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
            self._retrieve, req.message, self.settings.top_k_use)
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
                               self._lite(retrieved), citations, "traditional")

    # ================================================================ hybrid
    async def _run_hybrid(self, req: ChatRequest, conv_id: str, assistant_id: str,
                          history: list[dict]) -> AsyncGenerator[dict, None]:
        timings: dict[str, float] = {}
        decisions: list[dict] = []
        query = req.message

        # -- 1. broad retrieval -------------------------------------------------
        yield {"type": "status", "stage": "retrieving",
               "detail": f"broad embedding search (top {self.settings.top_k_retrieve})"}
        retrieved, timings["retrieval_ms"] = await asyncio.to_thread(
            self._retrieve, query, self.settings.top_k_retrieve)
        yield {"type": "retrieval", "retrieved": self._lite(retrieved)}

        if not retrieved:
            # nothing indexed yet: answer honestly with no context (no jev calls needed)
            model = self.settings.llm_model_default
            yield {"type": "sources", "citations": []}
            yield {"type": "llm_start", "model": model, "system": "hybrid"}
            usage: dict = {}
            async for evt in self._stream_llm(model, HYBRID_SYSTEM,
                                              build_user_message(query, "(no passages retrieved)"), history):
                if evt["type"] == "delta":
                    yield evt
                elif evt["type"] == "usage":
                    usage = evt["usage"]
            content = usage.get("_content", "")
            yield self._done_event(assistant_id, model, content, usage, timings, decisions,
                                   [], [], "hybrid")
            return

        # -- 2. Jev rerank (calibrated relevance, one decide() call) ------------
        yield {"type": "status", "stage": "jev-reranking",
               "detail": "local Jev-style engine scoring every passage (calibrated probabilities)"}
        ranked, rerank_rec = await asyncio.to_thread(
            self.jev.rerank_chunks, query, retrieved, self.settings.jev_rerank_char_limit)
        decisions.append(rerank_rec)
        timings["rerank_ms"] = rerank_rec["latency_ms"]
        yield {"type": "decision", "decision": rerank_rec}

        kept = ranked[: self.settings.top_k_use]
        yield {"type": "rerank", "kept": self._lite(kept)}

        # -- 3. sufficiency + model routing (one decide() call) -----------------
        labeled = self._label(kept)
        citations = self._citations(labeled)
        context_block = format_context(labeled)
        ctx_for_jev = "\n\n".join(
            f"Passage [{d['chunk_index_label']}] (source: {d['filename']}):\n"
            f"{d['text'][: self.settings.jev_context_char_limit]}"
            for d in labeled
        )
        model_options = {
            "default": (f"fast synthesis model ({self.settings.llm_model_default}): "
                        "direct factual answers grounded in the provided passages"),
            "reasoning": (f"deep reasoning model ({self.settings.llm_model_reasoning}): "
                          "complex multi-step analysis, comparisons or calculations"),
        }
        yield {"type": "status", "stage": "jev-routing",
               "detail": "context sufficiency gate + System Two model choice"}
        suf_p, chosen, probs, conf, recs = await asyncio.to_thread(
            self.jev.sufficiency_and_routing, query, ctx_for_jev, model_options)
        decisions.append(recs["sufficiency"])
        decisions.append(recs["routing"])
        timings["sufficiency_routing_ms"] = recs["sufficiency"]["latency_ms"]
        yield {"type": "decision", "decision": recs["sufficiency"]}
        yield {"type": "decision", "decision": recs["routing"]}

        model = (self.settings.llm_model_reasoning if chosen == "reasoning"
                 else self.settings.llm_model_default)
        yield {"type": "routing", "model": model,
               "probabilities": {k: round(v, 3) for k, v in probs.items()}, "confidence": conf}
        yield {"type": "sources", "citations": citations}

        # -- 4. System Two generates (streamed) ----------------------------------
        system = HYBRID_SYSTEM
        if suf_p < SUFFICIENCY_THRESHOLD:
            system += HYBRID_INSUFFICIENT_SUFFIX
        yield {"type": "llm_start", "model": model, "system": "hybrid",
               "context_sufficiency": round(suf_p, 3)}
        usage: dict = {}
        async for evt in self._stream_llm(model, system,
                                          build_user_message(query, context_block), history):
            if evt["type"] == "delta":
                yield evt
            elif evt["type"] == "usage":
                usage = evt["usage"]
        content = usage.get("_content", "")

        # -- 5. Jev groundedness verification ------------------------------------
        verification = None
        if self.settings.hybrid_verify_answers and content.strip():
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
                               self._lite(retrieved), citations, "hybrid", verification, suf_p)

    # ================================================================ helpers
    def _retrieve(self, query: str, k: int) -> tuple[list[dict], float]:
        t0 = time.perf_counter()
        embedding = self.embedder.embed_query(query)
        chunks: list[RetrievedChunk] = self.store.query(embedding, k)
        ms = (time.perf_counter() - t0) * 1000
        out: list[dict] = []
        for i, c in enumerate(chunks):
            d = c.as_dict()
            d["retrieval_rank"] = i + 1
            d["index"] = i + 1  # 1-based label used inside Jev rerank states
            out.append(d)
        return out, ms

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
                    },
                )
                session.add(msg)
                session.commit()
        except Exception as e:  # noqa: BLE001 — persistence must not kill the stream
            logger.error("failed to persist assistant message: %s", e)

    def _done_event(self, assistant_id: str, model: str, content: str, usage: dict,
                    timings: dict, decisions: list, retrieved: list, citations: list,
                    pipeline: str, verification: float | None = None,
                    sufficiency: float | None = None) -> dict:
        return {
            "type": "done", "message_id": assistant_id, "model": model, "content": content,
            "usage": {k: v for k, v in usage.items() if not k.startswith("_")},
            "cost_usd": estimate_cost_usd(model, usage.get("prompt_tokens", 0),
                                          usage.get("completion_tokens", 0)),
            "timings": timings, "decisions": decisions, "retrieved": retrieved,
            "citations": citations, "pipeline": pipeline,
            "verification": verification, "context_sufficiency": sufficiency,
        }
