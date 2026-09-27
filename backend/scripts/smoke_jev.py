"""Smoke test for the local Jev-Style decision engine (System One).

Validates: GGUF load, decide() with noul + choice, latency, and the exact
pipeline patterns used by app/llm/jev_engine.py.

Run: cd backend && .venv/bin/python -m scripts.smoke_jev
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Load backend .env manually (kept dependency-free of the app for isolation)
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


def main() -> int:
    print(f"model_dir: {MODEL_DIR}\nquant:     {QUANT}\nscorer:    {SCORER}")
    gguf = Path(MODEL_DIR) / f"Jev-Style-0.8B-Decision-v3-{QUANT}.gguf"
    if not gguf.is_file():
        print(f"FATAL: GGUF missing: {gguf}")
        return 1
    if not Path(SCORER).is_file():
        print(f"FATAL: scorer missing: {SCORER}")
        return 1

    from jev_style import JevStyle, choice, noul

    t0 = time.perf_counter()
    js = JevStyle(backend="gguf", model_dir=MODEL_DIR, quant=QUANT, scorer=SCORER)
    print(f"engine constructed in {time.perf_counter() - t0:.2f}s")

    # --- warm-up + basic noul ------------------------------------------------
    t0 = time.perf_counter()
    out = js.decide("The film was excellent, I loved every minute of it.",
                    {"pos": noul("This review is positive.")})
    dt = (time.perf_counter() - t0) * 1000
    print(f"\n[1] noul warm-up: P(positive)={out['answers']['pos']['noul']:.3f} "
          f"latency={dt:.0f}ms backend={out.get('backend')}")

    # --- rerank pattern (one state, many noul questions) ---------------------
    query = "What is the refund policy for annual subscriptions?"
    passages = {
        1: "Our refund policy allows full refunds within 30 days of purchase for all subscription plans.",
        2: "The team meets every Tuesday to discuss sprint planning and backlog grooming.",
        3: "Annual subscribers can request a pro-rated refund at any point during their billing cycle.",
        4: "The office kitchen has a new espresso machine and fresh fruit delivered on Mondays.",
    }
    state = f"Question: {query}\n\nPassages:\n" + "\n\n".join(f"[{i}] {t}" for i, t in passages.items())
    questions = {f"c{i}": noul(f"Passage [{i}] contains information relevant to answering the question.")
                 for i in passages}
    t0 = time.perf_counter()
    out = js.decide(state, questions)
    dt = (time.perf_counter() - t0) * 1000
    probs = {i: out["answers"][f"c{i}"]["noul"] for i in passages}
    print(f"\n[2] rerank pattern (4 passages, 1 call, {dt:.0f}ms):")
    for i, p in sorted(probs.items(), key=lambda kv: -kv[1]):
        marker = "KEEP" if p > 0.5 else "drop"
        print(f"    passage {i}: P(relevant)={p:.3f}  {marker}  «{passages[i][:60]}…»")

    # --- sufficiency + routing pattern (one call, mixed questions) -----------
    ctx = "Passage [1] (source: policy.pdf):\nRefunds are available within 30 days for monthly plans."
    t0 = time.perf_counter()
    out = js.decide(
        f"Question: {query}\n\n{ctx}",
        {
            "sufficiency": noul("The passages above contain sufficient information to answer the question completely."),
            "model": choice(
                "Which kind of model is better suited to answer this question well?",
                {
                    "default": "fast synthesis model: direct factual answers from provided context",
                    "reasoning": "deep reasoning model: complex multi-step analysis or calculations",
                },
            ),
        },
    )
    dt = (time.perf_counter() - t0) * 1000
    suf = out["answers"]["sufficiency"]["noul"]
    routing = out["answers"]["model"]
    print(f"\n[3] sufficiency+routing (1 call, {dt:.0f}ms):")
    print(f"    P(sufficient)={suf:.3f}  -> {'good context' if suf >= 0.5 else 'insufficient context'}")
    print(f"    routing -> {routing['choice']} (p={routing['probabilities']}, conf={routing['confidence']:.2f})")

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
