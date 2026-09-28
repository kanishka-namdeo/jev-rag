"""Experiment E: single-call rerank with passage text embedded in question instructions."""
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


def main() -> int:
    from jev_style import JevStyle, noul

    js = JevStyle(backend="gguf", model_dir=MODEL_DIR, quant=QUANT, scorer=SCORER)

    print("=== E) single call, passages inside question instructions ===")
    questions = {
        f"c{i}": noul(
            f"The following passage contains information relevant to answering the question "
            f"«{QUERY}». Passage: «{text}»"
        )
        for i, text in PASSAGES.items()
    }
    t0 = time.perf_counter()
    out = js.decide(f"Question: {QUERY}", questions)
    dt = (time.perf_counter() - t0) * 1000
    print(f"latency={dt:.0f}ms")
    for i in PASSAGES:
        p = out["answers"][f"c{i}"]["noul"]
        marker = "KEEP" if p > 0.5 else "drop"
        print(f"  passage {i}: P={p:.3f} {marker}")

    print("\n=== E2) single call, state = question, short generic statements ===")
    questions = {
        f"c{i}": noul(f"Passage {i} below is relevant to the question.")
        for i in PASSAGES
    }
    state = f"Question: {QUERY}\n\n" + "\n".join(
        f"Passage {i}: {t}" for i, t in PASSAGES.items())
    t0 = time.perf_counter()
    out = js.decide(state, questions)
    dt = (time.perf_counter() - t0) * 1000
    print(f"latency={dt:.0f}ms")
    for i in PASSAGES:
        p = out["answers"][f"c{i}"]["noul"]
        print(f"  passage {i}: P={p:.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
