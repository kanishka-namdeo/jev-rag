"""LLM-as-a-judge for RAG benchmark evaluation.

Protocol (grounded in MT-Bench / G-Eval / RAGAS judge-alignment guidance —
docs/benchmarking.md):
- Judge model is INDEPENDENT from both pipelines' generators (default kimi-k2.5:
  both RAG arms generate with qwen3.x-plus, so no self-preference bias).
- temperature=0, structured JSON output only, short reason for auditability.
- Absolute scoring per answer (RAGAS-style): correctness vs reference +
  faithfulness vs retrieved context + 3-way abstention classification
  (DeepEval AbstentionClassifier labels: answered | abstained | fabricated).
- Pairwise comparison runs BOTH orders (position-swap) and reports
  position-consistency; inconsistent verdicts resolve to tie (MT-Bench practice).
- self_test(): canary cases with known outcomes -> judge agreement score,
  stored on every run (RAGAS judge-alignment practice, lightweight variant).
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.config import Settings
from app.llm.dashscope import build_llm_client

logger = logging.getLogger("jevrag.bench.judge")

ABSOLUTE_SYSTEM = """You are an impartial evaluation judge for retrieval-augmented generation (RAG) systems.
Score the ANSWER on three dimensions using ONLY what is given:

1. correctness (0.0-1.0): factual agreement with the REFERENCE ANSWER (ground truth).
   1.0 = fully correct (semantic equivalence counts), 0.5 = partially correct
   (some facts right, some wrong/missing), 0.0 = wrong or no substantive answer.
2. faithfulness (0.0-1.0): fraction of the ANSWER's factual claims supported by the
   RETRIEVED CONTEXT. Unsupported or contradicted claims lower the score.
   1.0 = every claim supported; an answer adding unsupported facts scores below 1.0.
3. abstention, one of:
   - "abstained": the answer states the information is not available / insufficient
     to answer and gives no invented substance.
   - "answered": the answer gives a substantive response.
   - "fabricated": the answer responds confidently with content NOT supported by
     the retrieved context (hallucination).

Be strict. Length and style do not matter. Respond with ONLY a JSON object:
{"correctness": <float>, "faithfulness": <float>, "abstention": "answered|abstained|fabricated", "reason": "<one sentence>"}"""

PAIRWISE_SYSTEM = """You are an impartial judge comparing two answers (A and B) to the same question from two
RAG systems. Judge primarily by factual correctness against the REFERENCE ANSWER, then completeness,
then faithfulness to each answer's own context. Ignore verbosity and style unless they affect correctness.

Verdict: "A" if A is clearly better, "B" if B is clearly better, "tie" if roughly equal quality
or both equally wrong. Respond with ONLY a JSON object: {"winner": "A|B|tie", "reason": "<one sentence>"}"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json(text: str) -> dict | None:
    try:
        return json.loads(_FENCE_RE.sub("", text.strip()))
    except (json.JSONDecodeError, ValueError):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


class BenchJudge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = build_llm_client(settings, timeout=120.0)
        self.model = settings.bench_judge_model

    # ---------------------------------------------------------------- core call
    def _call(self, system: str, user: str, max_tokens: int = 400) -> dict | None:
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=0.0,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                parsed = _parse_json(resp.choices[0].message.content or "")
                if parsed is not None:
                    return parsed
                last_err = ValueError(f"unparseable judge output: {resp.choices[0].message.content!r:.200}")
            except Exception as e:  # noqa: BLE001 — judge failures must degrade, not crash runs
                last_err = e
                time.sleep(1.5)
        logger.warning("judge call failed after retries: %s", last_err)
        return None

    # ---------------------------------------------------------------- absolute
    def absolute(self, question: str, reference: str, context: str, answer: str) -> dict:
        user = (
            f"QUESTION: {question}\n\n"
            f"REFERENCE ANSWER (ground truth): {reference or '(no ground-truth answer: the question is unanswerable from the corpus)'}\n\n"
            f"RETRIEVED CONTEXT:\n{context or '(no context retrieved)'}\n\n"
            f"ANSWER TO EVALUATE:\n{answer}"
        )
        out = self._call(ABSOLUTE_SYSTEM, user)
        if out is None:
            return {"correctness": None, "faithfulness": None, "abstention": "error",
                    "reason": "judge call failed", "judge_error": True}
        try:
            corr = float(out.get("correctness"))
            corr = max(0.0, min(1.0, corr))
        except (TypeError, ValueError):
            corr = None
        try:
            faith = float(out.get("faithfulness"))
            faith = max(0.0, min(1.0, faith))
        except (TypeError, ValueError):
            faith = None
        abst = str(out.get("abstention", "answered")).lower()
        if abst not in ("answered", "abstained", "fabricated"):
            abst = "answered"
        return {"correctness": corr, "faithfulness": faith, "abstention": abst,
                "reason": str(out.get("reason", ""))[:400]}

    # ---------------------------------------------------------------- pairwise
    def _pairwise_once(self, question: str, reference: str,
                       ctx_a: str, ans_a: str, ctx_b: str, ans_b: str) -> str:
        user = (
            f"QUESTION: {question}\n\n"
            f"REFERENCE ANSWER (ground truth): {reference or '(unanswerable from corpus — prefer the answer that honestly abstains)'}\n\n"
            f"ANSWER A (with its retrieved context):\n--- context ---\n{ctx_a[:2000]}\n--- answer ---\n{ans_a}\n\n"
            f"ANSWER B (with its retrieved context):\n--- context ---\n{ctx_b[:2000]}\n--- answer ---\n{ans_b}"
        )
        out = self._call(PAIRWISE_SYSTEM, user, max_tokens=250)
        w = str((out or {}).get("winner", "tie")).upper()
        return w if w in ("A", "B", "TIE") else "TIE"

    def pairwise(self, question: str, reference: str,
                 trad: dict, hyb: dict) -> dict:
        """MT-Bench position-swap protocol: judge both orders, audit consistency.

        trad/hyb: {"context": str, "answer": str}
        Returns {"winner": "traditional"|"hybrid"|"tie", "position_consistent": bool}
        """
        # order 1: A=traditional, B=hybrid
        w1 = self._pairwise_once(question, reference,
                                 trad["context"], trad["answer"], hyb["context"], hyb["answer"])
        # order 2: A=hybrid, B=traditional (positions swapped)
        w2 = self._pairwise_once(question, reference,
                                 hyb["context"], hyb["answer"], trad["context"], trad["answer"])

        v1 = "tie" if w1 == "TIE" else ("traditional" if w1 == "A" else "hybrid")
        v2 = "tie" if w2 == "TIE" else ("hybrid" if w2 == "A" else "traditional")
        consistent = v1 == v2
        winner = v1 if consistent else "tie"   # inconsistent verdicts resolve to tie
        return {"winner": winner, "position_consistent": consistent,
                "verdict_order1": v1, "verdict_order2": v2}

    # ---------------------------------------------------------------- self-test
    def self_test(self) -> dict:
        """8 canary cases with known outcomes -> agreement score (RAGAS judge
        alignment practice). Cheap guard against a broken/misbehaving judge."""
        cases = [
            {  # 1 perfect answer
                "q": "What is the maximum message size in NimbusDB Pro tier?",
                "ref": "256 MB",
                "ctx": "NimbusDB Pro tier: messages up to 256 MB; Starter caps at 16 MB.",
                "ans": "The maximum message size for the Pro tier is 256 MB.",
                "expect": lambda r: r["correctness"] is not None and r["correctness"] >= 0.8
                                  and r["faithfulness"] is not None and r["faithfulness"] >= 0.9
                                  and r["abstention"] == "answered",
            },
            {  # 2 wrong number
                "q": "What is the maximum message size in NimbusDB Pro tier?",
                "ref": "256 MB",
                "ctx": "NimbusDB Pro tier: messages up to 256 MB; Starter caps at 16 MB.",
                "ans": "The maximum message size for the Pro tier is 512 MB.",
                "expect": lambda r: r["correctness"] is not None and r["correctness"] <= 0.3,
            },
            {  # 3 refusal on answerable
                "q": "What is the maximum message size in NimbusDB Pro tier?",
                "ref": "256 MB",
                "ctx": "NimbusDB Pro tier: messages up to 256 MB; Starter caps at 16 MB.",
                "ans": "The context does not contain information about the Pro tier message size, so I cannot answer.",
                "expect": lambda r: r["abstention"] == "abstained",
            },
            {  # 4 fabrication on unanswerable
                "q": "What is the orbital period of planet Gliese-7?",
                "ref": "",
                "ctx": "NimbusDB Pro tier: messages up to 256 MB.",
                "ans": "The orbital period of Gliese-7 is 62 Earth days.",
                "expect": lambda r: r["abstention"] == "fabricated" and r["faithfulness"] is not None
                                  and r["faithfulness"] <= 0.4,
            },
            {  # 5 proper abstention
                "q": "What is the orbital period of planet Gliese-7?",
                "ref": "",
                "ctx": "NimbusDB Pro tier: messages up to 256 MB.",
                "ans": "The retrieved passages do not contain any information about Gliese-7, so I cannot determine its orbital period.",
                "expect": lambda r: r["abstention"] == "abstained",
            },
            {  # 6 partially correct
                "q": "What are the retention periods for the Pro and Enterprise tiers?",
                "ref": "Pro: 30 days; Enterprise: 90 days",
                "ctx": "Retention: Starter 7 days, Pro 30 days, Enterprise 90 days.",
                "ans": "Pro retains data for 30 days; Enterprise retains data for 60 days.",
                "expect": lambda r: r["correctness"] is not None and 0.2 <= r["correctness"] <= 0.75,
            },
            {  # 7 correct + unsupported extra claim
                "q": "What is the maximum message size in NimbusDB Pro tier?",
                "ref": "256 MB",
                "ctx": "NimbusDB Pro tier: messages up to 256 MB.",
                "ans": "The Pro tier supports messages up to 256 MB. NimbusDB is the most widely deployed streaming platform in South America.",
                "expect": lambda r: r["correctness"] is not None and r["correctness"] >= 0.8
                                  and r["faithfulness"] is not None and r["faithfulness"] <= 0.7,
            },
            {  # 8 wrong entity (distractor confusion)
                "q": "What was Avalanche Robotics' Q3 revenue?",
                "ref": "$142.6 million",
                "ctx": "Northwind Analytics Q3 revenue was $142.8 million. Avalanche Robotics Q3 revenue was $142.6 million.",
                "ans": "Avalanche Robotics' Q3 revenue was $142.8 million.",
                "expect": lambda r: r["correctness"] is not None and r["correctness"] <= 0.4,
            },
        ]
        details = []
        passed = 0
        for i, c in enumerate(cases, 1):
            r = self.absolute(c["q"], c["ref"], c["ctx"], c["ans"])
            ok = bool(c["expect"](r))
            passed += ok
            details.append({"case": i, "ok": ok,
                            "got": {k: r.get(k) for k in ("correctness", "faithfulness", "abstention")}})
        return {"agreement": round(passed / len(cases), 3), "passed": passed,
                "total": len(cases), "details": details, "model": self.model}


class MultiJudgeEnsemble:
    """Multi-judge ensemble that aggregates scores across multiple judge models.

    This addresses judge bias and variance by using multiple independent judges
    from different model families. Aggregation uses:
    - Mean for continuous scores (correctness, faithfulness)
    - Majority vote for categorical decisions (abstention, pairwise winner)

    Reference: OpenJury framework, Cohere research on multi-judge reliability.
    """

    def __init__(self, settings: Settings, judge_models: list[str] | None = None):
        """Initialize ensemble with multiple judge models.

        Args:
            settings: Application settings
            judge_models: List of model names to use as judges. If None, uses
                         [settings.bench_judge_model] (single judge mode).
        """
        self.settings = settings
        self.judge_models = judge_models or [settings.bench_judge_model]
        self.judges = [self._create_judge(model) for model in self.judge_models]
        self.primary_model = self.judge_models[0] if self.judge_models else settings.bench_judge_model
        # Compatibility: runner.py expects self.judge.model
        self.model = self.primary_model

    def _create_judge(self, model: str) -> BenchJudge:
        """Create a BenchJudge instance for a specific model."""
        # Create a copy of settings with overridden judge model
        from copy import copy
        judge_settings = copy(self.settings)
        judge_settings.bench_judge_model = model
        return BenchJudge(judge_settings)

    def _call(self, system: str, user: str, max_tokens: int = 400) -> dict:
        """Compatibility: delegate to primary judge for context metrics."""
        return self.judges[0]._call(system, user, max_tokens)

    def absolute(self, question: str, reference: str, context: str, answer: str) -> dict:
        """Aggregate absolute scores across all judges.

        Returns dict with:
        - correctness: mean across judges
        - faithfulness: mean across judges
        - abstention: majority vote
        - agreement_*: inter-judge agreement metrics
        - individual_scores: per-judge results for debugging
        """
        if len(self.judges) == 1:
            # Single judge mode - return as-is
            return self.judges[0].absolute(question, reference, context, answer)

        # Collect scores from all judges
        results = []
        for judge in self.judges:
            result = judge.absolute(question, reference, context, answer)
            results.append(result)

        # Aggregate continuous scores (mean)
        correctness_scores = [r["correctness"] for r in results if r.get("correctness") is not None]
        faithfulness_scores = [r["faithfulness"] for r in results if r.get("faithfulness") is not None]

        avg_correctness = sum(correctness_scores) / len(correctness_scores) if correctness_scores else None
        avg_faithfulness = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else None

        # Aggregate categorical scores (majority vote)
        abstention_votes = [r.get("abstention", "answered") for r in results]
        majority_abstention = max(set(abstention_votes), key=abstention_votes.count)

        # Compute agreement metrics
        correctness_agreement = self._compute_agreement(correctness_scores) if len(correctness_scores) > 1 else 1.0
        faithfulness_agreement = self._compute_agreement(faithfulness_scores) if len(faithfulness_scores) > 1 else 1.0
        abstention_agreement = abstention_votes.count(majority_abstention) / len(abstention_votes)

        # Combine reasons (take first non-empty)
        reasons = [r.get("reason", "") for r in results if r.get("reason")]
        combined_reason = reasons[0] if reasons else ""

        return {
            "correctness": avg_correctness,
            "faithfulness": avg_faithfulness,
            "abstention": majority_abstention,
            "reason": combined_reason,
            "agreement_correctness": correctness_agreement,
            "agreement_faithfulness": faithfulness_agreement,
            "agreement_abstention": abstention_agreement,
            "n_judges": len(self.judges),
            "individual_scores": [
                {
                    "model": judge.model,
                    "correctness": r.get("correctness"),
                    "faithfulness": r.get("faithfulness"),
                    "abstention": r.get("abstention"),
                }
                for judge, r in zip(self.judges, results)
            ],
        }

    def pairwise(self, question: str, reference: str, trad: dict, hyb: dict) -> dict:
        """Aggregate pairwise comparisons across all judges.

        Returns dict with:
        - winner: majority vote across judges
        - position_consistent: True if all judges agree on direction
        - agreement: fraction of judges that agree with majority
        - individual_verdicts: per-judge results
        """
        if len(self.judges) == 1:
            # Single judge mode
            return self.judges[0].pairwise(question, reference, trad, hyb)

        # Collect verdicts from all judges
        results = []
        for judge in self.judges:
            result = judge.pairwise(question, reference, trad, hyb)
            results.append(result)

        # Extract winners (excluding ties for majority vote)
        winners = [r.get("winner", "tie") for r in results]
        non_tie_winners = [w for w in winners if w != "tie"]

        if non_tie_winners:
            # Majority vote among non-tie verdicts
            majority_winner = max(set(non_tie_winners), key=non_tie_winners.count)
            agreement = non_tie_winners.count(majority_winner) / len(non_tie_winners)
        else:
            # All ties
            majority_winner = "tie"
            agreement = 1.0

        # Check position consistency (all judges agree on direction)
        position_consistent = all(
            r.get("position_consistent", False) for r in results
        )

        return {
            "winner": majority_winner,
            "position_consistent": position_consistent,
            "agreement": agreement,
            "n_judges": len(self.judges),
            "individual_verdicts": [
                {
                    "model": judge.model,
                    "winner": r.get("winner"),
                    "position_consistent": r.get("position_consistent"),
                }
                for judge, r in zip(self.judges, results)
            ],
        }

    def _compute_agreement(self, scores: list[float]) -> float:
        """Compute inter-judge agreement for continuous scores.

        Uses 1 - coefficient_of_variation (CV) as agreement metric.
        CV = std / mean, so agreement = 1 - CV (clamped to [0, 1]).
        """
        if not scores or len(scores) < 2:
            return 1.0

        mean_score = sum(scores) / len(scores)
        if mean_score == 0:
            return 1.0

        variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
        std_score = variance ** 0.5
        cv = std_score / mean_score

        # Clamp agreement to [0, 1]
        agreement = max(0.0, min(1.0, 1.0 - cv))
        return round(agreement, 3)

    def self_test(self) -> dict:
        """Run self-test on primary judge (backward compatibility)."""
        # Use primary judge for self-test
        primary_judge = self.judges[0] if self.judges else BenchJudge(self.settings)
        return primary_judge.self_test()
