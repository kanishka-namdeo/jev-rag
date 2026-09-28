"""Experiment: decision patterns that replace model routing when only ONE
cloud LLM exists (single-generator degenerate case).

Motivation (research tasks 6-a / 6-b): with a single generator model, the
"which model should answer" routing slot degenerates into three families:
whether-to-call, how-to-call (effort/strategy), and which-candidate-to-keep.
This experiment measures whether our local Jev-Style-0.8B can actually own
those slots:

  A) effort routing      choice {no_retrieval, single_pass, multi_step}
                         per query, two state patterns (query-as-state vs
                         query-in-instructions) — Adaptive-RAG's A/B/C labels
  B) retrieval-need gate noul "requires searching the knowledge base"
                         (the no-retrieval arm: skips embedding search entirely)
  C) best-of-2 selection one decide() call, two noul questions — a faithful
                         answer vs a planted-hallucination answer; the verifier
                         becomes a selector
  D) citation check      one decide() call, three choice questions
                         (supports / contradicts / says_nothing) per claim
                         — the TypeSafe citation-check cookbook pattern

Run: backend/.venv/bin/python scripts/experiment_single_model_routing.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _repo_path(value: str) -> str:
    """Resolve relative values against the repo root (same anchoring as app config)."""
    p = Path(value).expanduser()
    return str(p if p.is_absolute() else (_REPO_ROOT / p))


MODEL_DIR = _repo_path(os.environ.get("JEVRAG_JEV_MODEL_DIR", "./models/jev-style"))
QUANT = os.environ.get("JEVRAG_JEV_QUANT", "Q4_K_M")
SCORER = _repo_path(os.environ.get("JEVRAG_JEV_SCORER", f"{MODEL_DIR}/build/jev-score"))

# ---------------------------------------------------------------- test data
# labels follow Adaptive-RAG's A/B/C taxonomy
QUERIES: list[tuple[str, str, str]] = [
    # (label, expected, note)
    ("Hi! What can you help me with?", "no_retrieval", "chit-chat"),
    ("Can you summarize our conversation so far?", "no_retrieval", "meta about chat"),
    ("What is the capital of France?", "no_retrieval", "general knowledge"),
    ("Write a short poem about autumn.", "no_retrieval", "creative"),
    ("What is the refund policy for annual subscriptions?", "single_pass", "factoid lookup"),
    ("How many concurrent connections does NimbusDB support?", "single_pass", "factoid lookup"),
    ("How many vacation days do new employees get?", "single_pass", "factoid lookup"),
    ("What is the maximum object storage per region?", "single_pass", "factoid lookup"),
    ("Compare Northwind's Q2 revenue with Avalanche's Q2 revenue.", "multi_step", "comparison of two docs"),
    ("Which of the SL200 and SL400 printers supports duplex printing, and what is its duty cycle?", "multi_step", "combine two specs"),
    ("What is the total revenue of both companies in Q3?", "multi_step", "aggregation"),
    ("Do the security requirements also apply to remote work arrangements?", "multi_step", "cross-document conditional"),
]

EFFORT_OPTIONS = {
    "no_retrieval": "a conversational, creative or general-knowledge request that does "
                    "not depend on any document collection",
    "single_pass": "a specific factual question answerable by looking up one document passage",
    "multi_step": "a question that requires combining, comparing or aggregating facts from "
                  "multiple documents or multiple sections",
}

# --- C) best-of-2 selection -------------------------------------------------
C_QUESTION = "What is the refund policy for annual subscriptions?"
C_CONTEXT = ("Annual subscribers may request a pro-rated refund at any point during their "
             "billing cycle, calculated from the remaining unused months.")
C_CANDIDATES = {
    "faithful": ("Annual subscribers can request a pro-rated refund at any point during their "
                 "billing cycle, based on the remaining unused months."),
    "tainted": ("Annual subscribers can request a full refund of the entire annual fee at any "
                "time, plus a 10% goodwill credit, and refunds are processed instantly."),
}

# --- D) citation check --------------------------------------------------------
D_PASSAGE = ("Refunds are processed within 5-10 business days and are returned to the "
             "original payment method. Expedited refunds are not offered.")
D_CLAIMS = {
    "supported": "Refunds take 5-10 business days to process.",
    "contradicted": "Refunds are issued instantly in cash.",
    "says_nothing": "The office kitchen has a new espresso machine.",
}
CITATION_OPTIONS = {
    "supports": "the passage states the information in the claim",
    "contradicts": "the passage states the opposite of the claim",
    "says_nothing": "the passage does not mention the subject of the claim",
}


def main() -> int:
    from jev_style import JevStyle, choice, noul

    js = JevStyle(backend="gguf", model_dir=MODEL_DIR, quant=QUANT, scorer=SCORER)

    # ================= A) effort routing — two state patterns =================
    print("=== A) effort routing (choice) — pattern 1: query as state ===")
    p1_hits = 0
    for q, expected, note in QUERIES:
        t0 = time.perf_counter()
        out = js.decide(f"User question: {q}", {
            "effort": choice("How much retrieval effort does answering this question require?",
                             EFFORT_OPTIONS),
        })
        dt = (time.perf_counter() - t0) * 1000
        got = out["answers"]["effort"]["choice"]
        ok = got == expected
        p1_hits += ok
        probs = {k: round(v, 2) for k, v in sorted(
            out["answers"]["effort"]["probabilities"].items(), key=lambda kv: -kv[1])}
        print(f"  [{'OK ' if ok else 'MISS'}] {expected:>13} -> {got:<13} conf={out['answers']['effort']['confidence']:.2f} "
              f"{probs} ({dt:.0f}ms)  «{q[:48]}» [{note}]")
    print(f"  pattern-1 accuracy: {p1_hits}/{len(QUERIES)}")

    print("\n=== A) effort routing (choice) — pattern 2: query inside instructions ===")
    p2_hits = 0
    for q, expected, note in QUERIES:
        t0 = time.perf_counter()
        out = js.decide("A user is asking a question in a document assistant.", {
            "effort": choice(
                f"How much retrieval effort does answering the question «{q}» require?",
                EFFORT_OPTIONS),
        })
        dt = (time.perf_counter() - t0) * 1000
        got = out["answers"]["effort"]["choice"]
        ok = got == expected
        p2_hits += ok
        probs = {k: round(v, 2) for k, v in sorted(
            out["answers"]["effort"]["probabilities"].items(), key=lambda kv: -kv[1])}
        print(f"  [{'OK ' if ok else 'MISS'}] {expected:>13} -> {got:<13} conf={out['answers']['effort']['confidence']:.2f} "
              f"{probs} ({dt:.0f}ms)  [{note}]")
    print(f"  pattern-2 accuracy: {p2_hits}/{len(QUERIES)}")

    # ================= B) retrieval-need gate (noul) ==========================
    print("\n=== B) retrieval-need gate (noul, threshold 0.5) ===")
    b_hits = 0
    for q, expected, _note in QUERIES:
        t0 = time.perf_counter()
        out = js.decide(
            f"User question: {q}",
            {"need": noul("Answering this question requires searching a private knowledge base "
                          "of company documents (policies, product docs, reports).")},
        )
        dt = (time.perf_counter() - t0) * 1000
        p = out["answers"]["need"]["noul"]
        predicted_need = p >= 0.5
        true_need = expected != "no_retrieval"
        ok = predicted_need == true_need
        b_hits += ok
        print(f"  [{'OK ' if ok else 'MISS'}] need={true_need!s:>5} -> P={p:.3f} ({dt:.0f}ms)  «{q[:48]}»")
    print(f"  retrieval-need accuracy: {b_hits}/{len(QUERIES)}")

    # ================= C) best-of-2 selection (one call, two nouls) ===========
    print("\n=== C) best-of-2 selection (single decide(): faithful vs tainted) ===")
    state = f"Question: {C_QUESTION}\n\nPassage:\n{C_CONTEXT}\n\nCandidate answers:"
    # note: candidates embedded in the instructions (the pattern that discriminates)
    t0 = time.perf_counter()
    out = js.decide(state, {
        f"cand_{name}": noul(
            f"The following proposed answer is fully supported by the passage above "
            f"(no fabricated numbers, policies or claims): «{text}»")
        for name, text in C_CANDIDATES.items()
    })
    dt = (time.perf_counter() - t0) * 1000
    scores = {name: out["answers"][f"cand_{name}"]["noul"] for name in C_CANDIDATES}
    winner = max(scores, key=scores.get)
    print(f"  faithful P={scores['faithful']:.3f}  tainted P={scores['tainted']:.3f}  "
          f"-> winner={winner} ({'OK' if winner == 'faithful' else 'MISS'}) ({dt:.0f}ms, one call)")

    # ================= D) citation check (one call, three choices) ============
    print("\n=== D) citation check (single decide(): supports/contradicts/says_nothing) ===")
    t0 = time.perf_counter()
    out = js.decide(f"Passage:\n{D_PASSAGE}", {
        f"claim_{name}": choice(
            f"Does the passage support this claim? Claim: «{claim}»",
            CITATION_OPTIONS)
        for name, claim in D_CLAIMS.items()
    })
    dt = (time.perf_counter() - t0) * 1000
    # label keys map to choice option keys ("supported" -> "supports" etc.)
    EXPECTED_OPTION = {"supported": "supports", "contradicted": "contradicts",
                       "says_nothing": "says_nothing"}
    d_hits = 0
    for name, claim in D_CLAIMS.items():
        ans = out["answers"][f"claim_{name}"]
        ok = ans["choice"] == EXPECTED_OPTION[name]
        d_hits += ok
        probs = {k: round(v, 2) for k, v in sorted(ans["probabilities"].items(),
                                                    key=lambda kv: -kv[1])}
        print(f"  [{'OK ' if ok else 'MISS'}] {name:>13} -> {ans['choice']:<13} conf={ans['confidence']:.2f} {probs}")
    print(f"  citation-check accuracy: {d_hits}/{len(D_CLAIMS)} ({dt:.0f}ms, one call)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
