#!/usr/bin/env python3
"""M6 splice: replace _run_hybrid with the v3 escalation design.

Gate inversion (docs/rag-upgrade-2026.md §3.3): always run cheap retrieval
first; escalate to the hard path on a calibrated score-feature gate instead of
asking the local model for absolute sufficiency judgments BEFORE retrieval.
Idempotent: skips when the v3 marker is already present.
"""
import sys

PATH = "/home/z/my-project/backend/app/rag/pipelines.py"

NEW = '''    # ================================================================ hybrid v3
    async def _run_hybrid(self, req: ChatRequest, conv_id: str, assistant_id: str,
                          history: list[dict]) -> AsyncGenerator[dict, None]:
        """v3 escalation design (docs/rag-upgrade-2026.md §3.3).

        [1] effort routing (jev, CONCURRENT with retrieval — only decides the
            chat-vs-doc question; validated P separation 0.76-0.96 vs <=0.17)
        [2] retrieval (RRF) + cross-encoder rerank — always, cheap
        [3] GATE (inverted: after retrieval, not before)
            features (default): top-1 rerank score vs calibrated threshold
            jev:                pre-v3 absolute sufficiency noul (testbench arm)
            none:               never escalate (testbench bounder)
            req.escalate (bench): overrides any gate (never/always/oracle arms)
        [4] EASY PATH (gate passes): one cloud call -> verify -> done
        [5] HARD PATH (gate fails): cloud decompose -> per-sub-query retrieval
            -> rerank -> optional battery -> CRAG corrective retry (cap 1)
            -> best-of-2 (jev selects — relative judgment) -> verify
        """
        s = self.settings
        timings: dict[str, float] = {}
        decisions: list[dict] = []
        query = req.message
        model = s.llm_model_default  # single generator
        extra: dict[str, Any] = {"effort": "single_pass", "path": "easy"}

        # -- [1] effort routing, concurrent with first retrieval ----------------
        kb_empty = await asyncio.to_thread(self.store.count) == 0

        async def _route():
            if kb_empty or not s.hybrid_effort_routing:
                return ("single_pass", {}, 0.0, None)
            effort, eprobs, econf, rec = await asyncio.to_thread(
                self.jev.effort_routing, query)
            return effort, eprobs, econf, rec

        async def _first_retrieve():
            if kb_empty:
                return [], 0.0
            return await asyncio.to_thread(
                self._retrieve, query, s.top_k_retrieve, req.doc_ids)

        (effort, eprobs, econf, route_rec), (retrieved, retrieval_ms) = \\
            await asyncio.gather(_route(), _first_retrieve())
        if route_rec is not None:
            decisions.append(route_rec)
            timings["effort_ms"] = route_rec["latency_ms"]
            yield {"type": "decision", "decision": route_rec}
        timings["retrieval_ms"] = retrieval_ms
        extra["effort"] = effort

        if (effort == "no_retrieval"
                and eprobs.get("no_retrieval", 0.0) >= s.jev_no_retrieval_threshold):
            # Adaptive-RAG class A: skip retrieval entirely (validated fast path)
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

        # -- [2] rerank the first pool --------------------------------------------
        ranked, rerank_rec = await asyncio.to_thread(self._rerank, query, retrieved)
        decisions.append(rerank_rec)
        timings["rerank_ms"] = rerank_rec["latency_ms"]
        yield {"type": "decision", "decision": rerank_rec}
        kept = ranked[: s.top_k_use]
        yield {"type": "rerank", "kept": self._lite(kept)}

        # -- [3] GATE: escalate to the hard path? ---------------------------------
        gate_p, gate_rec, escalate = await asyncio.to_thread(self._gate, query, kept, req)
        if gate_rec is not None:
            decisions.append(gate_rec)
            timings["gate_ms"] = gate_rec["latency_ms"]
            yield {"type": "decision", "decision": gate_rec}
        extra["gate"] = {"mode": s.gate_mode, "p": round(gate_p, 4) if gate_p is not None else None,
                         "escalated": escalate}

        labeled: list[dict] = []
        context_block = ""
        ctx_for_jev = ""
        conflict: list[dict] = []
        suf_p = gate_p

        if not escalate:
            # -- [4] EASY PATH: exactly one cloud call, no local LLM on hot path -
            extra["path"] = "easy"
            labeled = self._label(kept)
            conflict = []
            context_block = format_context(labeled)
            ctx_for_jev = self._ctx_for_jev(labeled, s)
        else:
            # -- [5] HARD PATH: decompose -> retrieve per sub-query -> gate/retry -
            extra["path"] = "hard"
            extra["effort"] = "multi_step"
            yield {"type": "status", "stage": "escalating",
                   "detail": "gate flagged low confidence — decomposing the question "
                             "and retrieving per sub-query"}
            sub_queries: list[str] = []
            if s.hybrid_multistep:
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
            if len(sub_queries) > 1:
                retrieved, timings["retrieval_ms"] = await asyncio.to_thread(
                    self._retrieve_multi, sub_queries, req.doc_ids)
            else:
                retrieved, timings["retrieval_ms"] = await asyncio.to_thread(
                    self._retrieve, query, s.top_k_retrieve, req.doc_ids)
            yield {"type": "retrieval", "retrieved": self._lite(retrieved)}

            # rerank -> battery -> gate, with one corrective retry
            search_query = query
            rewritten_query: str | None = None
            max_attempts = 2 if s.hybrid_corrective_retry else 1
            screen: dict[str, Any] | None = None
            for attempt in range(max_attempts):
                if attempt == 1:
                    # CRAG corrective loop (capped at 1): rewrite -> re-retrieve
                    yield {"type": "status", "stage": "jev-gating",
                           "detail": "context still insufficient — rewriting the query and retrying retrieval"}
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
                    self._rerank, search_query, retrieved)
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
                    context_block += "\\n\\n" + format_conflict_block(flagged)
                ctx_for_jev = self._ctx_for_jev(labeled, s)

                suf_p, gate_rec, _ = await asyncio.to_thread(self._gate, query, kept, req)
                if gate_rec is not None:
                    decisions.append(gate_rec)
                    yield {"type": "decision", "decision": gate_rec}
                extra["gate"]["p_final"] = round(suf_p, 4) if suf_p is not None else None

                screen = {"labeled": labeled, "main": main, "flagged": flagged,
                          "context_block": context_block, "ctx_for_jev": ctx_for_jev,
                          "suf_p": suf_p, "kept": kept}
                if self._gate_passes(suf_p):
                    break

            if screen is None:
                # corrective retry also found nothing: honest no-context answer
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
            conflict = screen["flagged"]
            extra.update({"retried": rewritten_query is not None,
                          "rewritten_query": rewritten_query,
                          "conflict_passages": len(conflict)})

        citations = self._citations(labeled)
        yield {"type": "sources", "citations": citations}

        # -- generation: easy path streams; hard path may do best-of-2 ----------
        system = HYBRID_SYSTEM
        if extra["path"] == "hard" and not self._gate_passes(suf_p):
            system += HYBRID_INSUFFICIENT_SUFFIX
        if conflict:
            system += HYBRID_CONFLICT_SUFFIX
        user_msg = build_user_message(query, context_block)

        best_of = (s.hybrid_best_of_n and extra["path"] == "hard"
                   and (not self._gate_passes(suf_p) or effort == "multi_step"))
        usage = {}
        content = ""
        if best_of:
            # Speculative-RAG-style sampling: two candidates from the SAME generator
            # (thinking off / thinking on), then ONE Jev call picks the winner by
            # calibrated P(grounded) — a relative selector.
            yield {"type": "status", "stage": "answering",
                   "detail": "sampling 2 candidates (direct + reasoned) — Jev will select"}
            yield {"type": "llm_start", "model": model, "system": "hybrid",
                   "context_sufficiency": round(suf_p, 3) if suf_p is not None else None,
                   "best_of": 2}
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
            parts = content.split("\\n\\n")
            for i, part in enumerate(parts):
                yield {"type": "delta", "content": part + ("\\n\\n" if i < len(parts) - 1 else "")}
        else:
            yield {"type": "llm_start", "model": model, "system": "hybrid",
                   "context_sufficiency": round(suf_p, 3) if suf_p is not None else None}
            async for evt in self._stream_llm(model, system, user_msg, history):
                if evt["type"] == "delta":
                    yield evt
                elif evt["type"] == "usage":
                    usage = evt["usage"]
            timings["llm_ms"] = usage.get("_llm_ms", 0.0)
            content = usage.get("_content", "")

        # -- citation verification + composite quality (jev, post-answer) --------
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
                               round(suf_p, 3) if suf_p is not None else None,
                               extra=self._ctx(req, context_block, extra))

    # -- v3 gate helpers -----------------------------------------------------
    def _gate_passes(self, p: float | None) -> bool:
        """Gate verdict from a gate probability. features mode: the reranker's
        top-1 calibrated score vs gate_score_threshold; jev mode: the noul
        sufficiency vs jev_sufficiency_threshold (pre-v3 semantics)."""
        if p is None:
            return False
        if self.settings.gate_mode == "features":
            return p >= self.settings.gate_score_threshold
        return p >= self.settings.jev_sufficiency_threshold

    def _gate(self, query: str, kept: list[dict],
              req: ChatRequest) -> tuple[float | None, dict | None, bool]:
        """Evaluate the escalation gate. Returns (gate_p, decision record | None,
        escalate). req.escalate (bench-injected) overrides everything — that is
        how the never/always/oracle bounder arms run."""
        s = self.settings
        t0 = time.perf_counter()
        if req.escalate is not None:
            escalate = bool(req.escalate)
            rec = {
                "name": "gate", "label": f"Escalation gate (injected: "
                                         f"{'hard' if escalate else 'easy'} path)",
                "kind": "score",
                "question": "bench-injected override (never/always/oracle arm)",
                "answer": "escalate" if escalate else "easy",
                "probabilities": None, "confidence": None,
                "latency_ms": 0.0, "usage": None, "mode": "injected",
            }
            return None, rec, escalate

        if s.gate_mode == "none":
            # never escalate — the bounder arm; record the features it skipped
            feats = self._gate_features(kept)
            rec = {
                "name": "gate", "label": "Escalation gate (disabled — never escalate)",
                "kind": "score", "question": "none (bounder arm)",
                "answer": "easy", "probabilities": feats,
                "confidence": None, "latency_ms": 0.0, "usage": None, "mode": "none",
            }
            return feats.get("top1"), rec, False

        if s.gate_mode == "jev":
            # pre-v3 behaviour: absolute sufficiency noul (testbench arm)
            ctx = self._ctx_for_jev(self._label(kept), s)
            p, rec = self.jev.sufficiency(query, ctx)
            rec["name"] = "gate"
            rec["label"] = "Escalation gate (jev absolute sufficiency)"
            rec["mode"] = "jev"
            return p, rec, not self._gate_passes(p)

        # features (default): calibrated top-1 rerank score + distribution stats
        feats = self._gate_features(kept)
        top1 = feats.get("top1")
        p = top1
        escalate = not self._gate_passes(p)
        rec = {
            "name": "gate", "label": "Escalation gate (score features)",
            "kind": "score",
            "question": f"top-1 rerank score vs threshold {s.gate_score_threshold} "
                        "(+ margin / mean / count-above-floor for the trace)",
            "answer": "escalate" if escalate else "easy",
            "probabilities": {k: round(v, 3) if v is not None else None
                              for k, v in feats.items()},
            "confidence": None, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "usage": None, "mode": "features",
            "threshold": s.gate_score_threshold,
        }
        return p, rec, escalate

    def _gate_features(self, kept: list[dict]) -> dict:
        """Retrieval-grounded score features (R2 research: cheap calibrated
        signals replace unreliable zero-shot LLM sufficiency judgments)."""
        if not kept:
            return {"top1": 0.0, "top2": 0.0, "margin": 0.0, "mean": 0.0, "above_floor": 0}
        scores = [float(c.get("jev_score", 0.0) or 0.0) for c in kept]
        floor = self.settings.gate_score_threshold
        top2 = scores[1] if len(scores) > 1 else 0.0
        return {
            "top1": round(scores[0], 4),
            "top2": round(top2, 4),
            "margin": round(scores[0] - top2, 4),
            "mean": round(sum(scores) / len(scores), 4),
            "above_floor": sum(1 for sc in scores if sc >= floor),
        }

    @staticmethod
    def _ctx_for_jev(labeled: list[dict], s: Settings) -> str:
        return "\\n\\n".join(
            f"Passage [{d['chunk_index_label']}] (source: {d['filename']}):\\n"
            f"{d['text'][: s.jev_context_char_limit]}"
            for d in labeled
        )

'''


def main() -> int:
    with open(PATH) as f:
        src = f.read()
    if "_gate_features" in src:
        print("already spliced — nothing to do")
        return 0
    start = src.index("    # ================================================================ hybrid v2")
    end = src.index("    # ================================================================ helpers")
    src = src[:start] + NEW + src[end:]
    with open(PATH, "w") as f:
        f.write(src)
    print("spliced OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
