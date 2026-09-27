"""Local Jev-style decision engine (System One).

Wraps the open-source `jev-style` package (github.com/lawrence3699/jev-style) running
chaoliangUNSW/Jev-Style-0.8B-Decision-v3-GGUF (Apache-2.0, 0.53 GB Q4_K_M) on llama.cpp
via the `jev-score` scorer — typed, calibrated decisions (noul / choice / score),
Jev-faithful: it never generates text, it decides.

Pipeline roles:
- rerank       one decide() call: state = question + passages, one noul question per passage
- sufficiency  noul: "the passages are sufficient to answer"
- routing      choice: which cloud model should answer
- verification noul: "the answer is fully supported by the passages"

Memory: the jev-score subprocess runs with a reduced llama.cpp context
(`JEV_SCORE_N_CTX`, default 8192) — our states stay under ~3k tokens, and the stock
32k context allocated ~900MB of KV cache that repeatedly triggered sandbox OOM kills.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.config import Settings

logger = logging.getLogger("jevrag.jev")


class JevEngineUnavailable(RuntimeError):
    pass


class JevEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._js: Any | None = None
        self._load_error: str | None = None
        self._info: dict[str, Any] = {}

    # ---------------------------------------------------------------- lifecycle
    def load(self) -> bool:
        """Idempotent load. Returns availability; never raises."""
        if self._js is not None or self._load_error is not None:
            return self._js is not None
        if not self.settings.jev_enabled:
            self._load_error = "jev engine disabled by settings"
            return False
        t0 = time.perf_counter()
        try:
            # Reduced llama.cpp context BEFORE the runtime import (the module reads
            # it at import time). Must be set before `from jev_style import ...`.
            os.environ.setdefault("JEV_SCORE_N_CTX", str(self.settings.jev_score_n_ctx))
            from jev_style import JevStyle  # deferred import: heavy at module import time

            kwargs: dict[str, Any] = {
                "model_dir": str(self.settings.jev_model_dir_path),
                "quant": self.settings.jev_quant,
            }
            scorer = self.settings.jev_scorer_path
            if scorer:
                kwargs["scorer"] = str(scorer)
            self._js = JevStyle(backend="gguf", **kwargs)
            # Warm-up decision so the first real query pays no cold-start cost.
            warm = self._js.decide("warmup", {"ok": {"type": "noul", "instructions": "The system is warm."}})
            self._info = {
                "model": warm.get("model", "jev-style-0.8b-decision-v3"),
                "backend": warm.get("backend", "gguf"),
                "load_seconds": round(time.perf_counter() - t0, 2),
            }
            logger.info("jev engine ready in %.2fs: %s", self._info["load_seconds"], self._info)
            return True
        except Exception as e:  # noqa: BLE001 — load failure must degrade, not crash, the app
            self._load_error = f"{type(e).__name__}: {e}"
            logger.error("jev engine failed to load: %s", self._load_error)
            return False

    @property
    def available(self) -> bool:
        return self._js is not None

    def info(self) -> dict[str, Any]:
        return {
            "ok": self.available,
            "engine": "jev-style (open-source Jev-style decisions)",
            "model_dir": str(self.settings.jev_model_dir_path),
            "quant": self.settings.jev_quant,
            "scorer": str(self.settings.jev_scorer_path or "(runtime lookup)"),
            **({"error": self._load_error} if self._load_error else {}),
            **self._info,
        }

    # ---------------------------------------------------------------- raw call
    def _decide(self, state: Any, questions: dict[str, dict]) -> dict:
        """One decide() call with automatic recovery.

        The jev-score subprocess can be killed by the OS (sandbox OOM under
        memory pressure) and can fail to start when memory is transiently
        exhausted. Recovery policy:
        - engine not loaded / previous load failed -> attempt ONE fresh load
          (a later call succeeds once memory pressure subsides);
        - subprocess dies mid-call -> reload once and retry the call,
          so a single kill does not poison the whole app/session.
        """
        if self._js is None:
            if not self._try_load():
                raise JevEngineUnavailable(self._load_error or "jev engine not loaded")
        try:
            return self._js.decide(state, questions)
        except Exception as e:  # noqa: BLE001 — attempt one recovery reload
            logger.warning("jev decide failed (%s: %s) — reloading engine once",
                           type(e).__name__, e)
            if self._try_load():
                try:
                    return self._js.decide(state, questions)  # type: ignore[union-attr]
                except Exception as e2:  # noqa: BLE001 — dead again after reload
                    raise JevEngineUnavailable(
                        f"jev engine died again after reload ({type(e2).__name__}: {e2})") from e2
            raise JevEngineUnavailable(
                f"jev engine died ({type(e).__name__}: {e}) and reload failed: "
                f"{self._load_error}") from e

    def _try_load(self) -> bool:
        """Force a fresh JevStyle load (spawns a new jev-score subprocess),
        clearing any previous load-failure state first."""
        self._js = None
        self._load_error = None
        return self.load()

    def _noul(self, instructions: str) -> dict:
        return {"type": "noul", "instructions": instructions}

    def _choice(self, instructions: str, options: dict[str, str]) -> dict:
        return {"type": "choice", "instructions": instructions,
                "criteria": {k: v for k, v in options.items()}}

    def _record(self, name: str, label: str, kind: str, question: str, answer: Any,
                probabilities: dict[str, float] | None, confidence: float | None,
                latency_ms: float, usage: dict | None) -> dict:
        return {
            "name": name, "label": label, "kind": kind, "question": question,
            "answer": answer, "probabilities": probabilities, "confidence": confidence,
            "latency_ms": round(latency_ms, 1), "usage": usage,
        }

    # ---------------------------------------------------------------- pipeline ops
    def rerank_chunks(self, query: str, chunks: list[dict], char_limit: int) -> tuple[list[dict], dict]:
        """Calibrated relevance per passage in ONE decide() call (state read once).

        Pattern validated experimentally (backend/scripts/experiment_rerank*.py):
        each noul question embeds one passage's text in its instructions; the shared
        state is the query. Discriminates relevant (P≈0.97) from distractors (P≈0.02).

        chunks: [{index, chunk_id, text, ...}] -> (ranked chunks with jev_score, decision record)
        """
        questions = {
            f"c{c['index']}": self._noul(
                f"The following passage contains information relevant to answering the question "
                f"«{query}». Passage: «{c['text'][:char_limit]}»"
            )
            for c in chunks
        }
        t0 = time.perf_counter()
        out = self._decide(f"Question: {query}", questions)
        elapsed = (time.perf_counter() - t0) * 1000
        probs: dict[int, float] = {}
        for c in chunks:
            ans = out["answers"].get(f"c{c['index']}", {})
            probs[c["index"]] = float(ans.get("noul", 0.0))
        ranked = sorted(chunks, key=lambda c: probs.get(c["index"], 0.0), reverse=True)
        for c in ranked:
            c["jev_score"] = probs.get(c["index"], 0.0)
        record = self._record(
            name="rerank", label="Jev rerank (calibrated relevance per passage)", kind="noul",
            question="For each passage: does it contain information relevant to the question?",
            answer={f"passage {i}": round(p, 3) for i, p in sorted(probs.items())},
            probabilities={f"[{i}]": p for i, p in probs.items()},
            confidence=None, latency_ms=elapsed, usage=out.get("usage"),
        )
        return ranked, record

    def sufficiency_and_routing(
        self, query: str, context_block: str, model_options: dict[str, str],
    ) -> tuple[float, str, dict[str, float], float, dict]:
        """One decide() call answering both: is context sufficient + which model should answer.

        model_options maps a short key (used as the choice option) -> description.
        Returns (sufficiency_p, chosen_key, probabilities, confidence, decision_record_pair).
        """
        state = f"Question: {query}\n\n{context_block}"
        questions = {
            "sufficiency": self._noul(
                "The passages above contain sufficient information to answer the question completely "
                "and accurately."
            ),
            "model": self._choice(
                "Which kind of model is better suited to answer this question well?",
                model_options,
            ),
        }
        t0 = time.perf_counter()
        out = self._decide(state, questions)
        elapsed = (time.perf_counter() - t0) * 1000
        suf_ans = out["answers"]["sufficiency"]
        model_ans = out["answers"]["model"]
        sufficiency_p = float(suf_ans.get("noul", 0.0))
        probs = {k: float(v) for k, v in model_ans.get("probabilities", {}).items()}
        chosen = model_ans.get("choice", next(iter(model_options)))
        records = {
            "sufficiency": self._record(
                name="sufficiency", label="Jev sufficiency gate", kind="noul",
                question="Do the passages contain sufficient information to answer completely?",
                answer=round(sufficiency_p, 3), probabilities={"false": round(1 - sufficiency_p, 3),
                                                               "true": round(sufficiency_p, 3)},
                confidence=None, latency_ms=elapsed, usage=out.get("usage"),
            ),
            "routing": self._record(
                name="routing", label="Jev model routing (System Two choice)", kind="choice",
                question="Which cloud model should answer?", answer=chosen,
                probabilities={k: round(v, 3) for k, v in probs.items()},
                confidence=model_ans.get("confidence"), latency_ms=0.0, usage=None,
            ),
        }
        return sufficiency_p, chosen, probs, float(model_ans.get("confidence", 0.0)), records

    def verify_groundedness(self, query: str, answer: str, context_block: str) -> tuple[float, dict]:
        t0 = time.perf_counter()
        state = f"Question: {query}\n\n{context_block}\n\nProposed answer:\n{answer}"
        out = self._decide(state, {
            "grounded": self._noul(
                "The proposed answer is fully supported by the passages above (no unsupported claims)."
            ),
        })
        elapsed = (time.perf_counter() - t0) * 1000
        p = float(out["answers"]["grounded"].get("noul", 0.0))
        record = self._record(
            name="verification", label="Jev groundedness check", kind="noul",
            question="Is the answer fully supported by the passages?",
            answer=round(p, 3), probabilities={"false": round(1 - p, 3), "true": round(p, 3)},
            confidence=None, latency_ms=elapsed, usage=out.get("usage"),
        )
        return p, record
