"""Experiment: which rerank pattern actually discriminates relevance?

A) choice over passages (one call, ranking distribution)
B) per-passage noul with passage-as-state (N calls)
C) noul phrasing variant with passage text inside the question
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

MODEL_DIR = os.environ.get("JEVRAG_JEV_MODEL_DIR", "/home/z/my-project/models/jev-style")
QUANT = os.environ.get("JEVRAG_JEV_QUANT", "Q4_K_M")
SCORER = os.environ.get("JEVRAG_JEV_SCORER", f"{MODEL_DIR}/build/jev-score")

QUERY = "What is the refund policy for annual subscriptions?"
PASSAGES = {
    1: "Our refund policy allows full refunds within 30 days of purchase for all subscription plans.",
    2: "The team meets every Tuesday to discuss sprint planning and backlog grooming.",
    3: "Annual subscribers can request a pro-rated refund at any point during their billing cycle.",
    4: "The office kitchen has a new espresso machine and fresh fruit delivered on Mondays.",
}
EXPECTED = [1, 3]  # relevant; 2 and 4 are distractors


def main() -> int:
    from jev_style import JevStyle, choice, noul

    js = JevStyle(backend="gguf", model_dir=MODEL_DIR, quant=QUANT, scorer=SCORER)

    print("=== A) choice over passages (one call) ===")
    state = f"Question: {QUERY}\n\nPassages:\n" + "\n\n".join(
        f"[{i}] {t}" for i, t in PASSAGES.items())
    t0 = time.perf_counter()
    out = js.decide(state, {
        "best": choice(
            "Which passage is the most relevant to answering the question?",
            {f"passage_{i}": f"passage [{i}]" for i in PASSAGES},
        )
    })
    dt = (time.perf_counter() - t0) * 1000
    ans = out["answers"]["best"]
    print(f"latency={dt:.0f}ms choice={ans['choice']} conf={ans['confidence']:.2f}")
    for k, v in sorted(ans["probabilities"].items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v:.3f}")

    print("\n=== B) per-passage noul, passage-as-state (N calls) ===")
    total = 0.0
    for i, text in PASSAGES.items():
        t0 = time.perf_counter()
        out = js.decide(
            f"Question: {QUERY}\n\nPassage:\n{text}",
            {"rel": noul("The passage contains information relevant to answering the question.")},
        )
        dt = (time.perf_counter() - t0) * 1000
        total += dt
        p = out["answers"]["rel"]["noul"]
        marker = "KEEP" if p > 0.5 else "drop"
        print(f"  passage {i}: P={p:.3f} ({dt:.0f}ms) {marker}")
    print(f"  total: {total:.0f}ms")

    print("\n=== C) per-passage noul, question phrasing 'answers the question' ===")
    for i, text in PASSAGES.items():
        t0 = time.perf_counter()
        out = js.decide(
            f"Question: {QUERY}\n\nPassage:\n{text}",
            {"rel": noul("The passage contains information that answers the question.")},
        )
        dt = (time.perf_counter() - t0) * 1000
        p = out["answers"]["rel"]["noul"]
        print(f"  passage {i}: P={p:.3f} ({dt:.0f}ms)")

    print("\n=== D) per-passage score (levels) ===")
    for i, text in PASSAGES.items():
        t0 = time.perf_counter()
        out = js.decide(
            f"Question: {QUERY}\n\nPassage:\n{text}",
            {"rel": {"type": "score",
                     "instructions": "How relevant is the passage to the question?",
                     "criteria": ["irrelevant", "partially relevant", "highly relevant"]}},
        )
        dt = (time.perf_counter() - t0) * 1000
        a = out["answers"]["rel"]
        print(f"  passage {i}: score={a['score']:.2f} probs={ {k: round(v,3) for k,v in a['probabilities'].items()} } ({dt:.0f}ms)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
