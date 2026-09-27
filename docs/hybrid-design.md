# Hybrid design: Jev-style System One + cloud System Two

## What "Jev" is (researched, not assumed)

- **Jev** (TypeSafe AI, Sep 2026) is a *closed-weights, cloud-only* "System One" decision model.
  It does **not generate text** — it answers typed questions with calibrated probabilities:
  `Choice` (pick an option), `Score` (rubric rating), `Noul` (P(statement is true)).
  Sources: [typesafe.ai blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev),
  [docs.typesafe.ai](https://docs.typesafe.ai/introduction), [LangChain blog](https://www.langchain.com/blog/building-a-harness-with-jev).
  No published weights exist (verified: HF org `TypeSafeAI` ships only Step-5-Preview, not Jev).

- Therefore we run the **open-source Jev-style equivalent**:
  [chaoliangUNSW/Jev-Style-0.8B-Decision-v3-GGUF](https://huggingface.co/chaoliangUNSW/Jev-Style-0.8B-Decision-v3-GGUF)
  (Apache-2.0, 0.53 GB in Q4_K_M) via the
  [jev-style](https://github.com/lawrence3699/jev-style) package — a systemone-compatible,
  local, llama.cpp-backed implementation of the same decision pattern (single verdict-slot
  logit readout, calibrated probabilities, up to 25.6k-token states, 19 languages).

## Why decisions-only is Jev-faithful

The hybrid pipeline keeps the division of labor the Jev concept implies:

- **System One (local, fast, calibrated, cheap)** decides: which passages matter, whether the
  context suffices, which System Two model should answer, whether the answer is grounded.
- **System Two (cloud, deliberative)** writes the final prose.

## Decision points in the pipeline

| Step | Primitive | State | Question |
| --- | --- | --- | --- |
| Rerank | noul × N passages (one call) | `Question: {q}` | "The following passage contains information relevant to answering the question «q». Passage: «…»" |
| Sufficiency | noul (shared call) | question + kept passages (truncated) | "The passages above contain sufficient information to answer the question completely and accurately." |
| Routing | choice (shared call) | same state | options: fast synthesis model vs deep reasoning model |
| Verification | noul | question + passages + answer | "The proposed answer is fully supported by the passages above." |

## Validated decision patterns (experiments in `backend/scripts/`)

Measured on this sandbox (2 CPU cores, Q4_K_M):

| Pattern | Result | Latency |
| --- | --- | --- |
| Shared-state generic statements ("passage i is relevant") | **fails** — no discrimination (all ≈0.95) | — |
| Choice over passages | partial ranking, low confidence | ~1.5 s |
| **Passage text embedded in the noul instructions, one call** | **correct**: relevant 0.97 / distractor 0.02 | ~3 s for 4 passages |
| Passage-as-state, N calls | correct but N× latency | ~0.85 s/passage |
| Score (3 levels) | correct, richer signal, same cost | ~0.85 s/passage |

Chosen pattern: passage text embedded in question instructions, single `decide()` call —
the state is read once and every passage gets a calibrated verdict slot.

## Cloud model routing (System Two)

| Model | Released | Price (in/out per Mtok) | Role here |
| --- | --- | --- | --- |
| qwen3.7-plus | 2026-05-31 | $0.32 / $1.28 | default synthesis (fast, cheap, agentic) |
| qwen3.6-plus | 2026-03-31 | $0.50 / $3.00 | deep-reasoning route (always-on CoT) |

Sources: llm-stats.com model pages, qwen.ai blog posts, live endpoint model list (verified
2026-09-27). The Jev `choice` routes between them per query; probabilities are shown in the UI.

## Latency profile (this sandbox, 3-passage doc)

- Traditional end-to-end: ~1.9 s (retrieval 12 ms + LLM 1.8 s)
- Hybrid end-to-end: ~15 s (rerank ~3.7 s + sufficiency/routing ~6.7 s + LLM ~2 s + verify ~3.6 s)
- Knobs to trade latency vs rigor: `JEVRAG_TOP_K_RETRIEVE`, `JEVRAG_JEV_RERANK_CHAR_LIMIT`,
  `JEVRAG_JEV_CONTEXT_CHAR_LIMIT`, `JEVRAG_HYBRID_VERIFY_ANSWERS`.
