# Hybrid design: Jev-style System One + cloud System Two

> **v3 (2026-09-29):** the hybrid pipeline was redesigned around a score-feature escalation gate.
> The absolute sufficiency gate (v2) was replaced with calibrated retrieval scores, limiting Jev
> to 3 relative judgments (effort routing, best-of-2, citations). The v2 7-slot design is documented
> below as historical context; v1 details remain at the end. See [rag-upgrade-2026.md](rag-upgrade-2026.md)
> for the full v3 design rationale and measured results.

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

- **System One (local, fast, calibrated, cheap)** decides: how much retrieval effort a question
  needs, which sampled candidate to keep, whether each citation holds.
- **System Two (cloud, deliberative)** writes the final prose — one model, not two.

**v3 key insight:** A ~0.5B decision model cannot make reliable *absolute* judgments (sufficiency,
relevance thresholds). The v3 design uses Jev only for **relative judgments** (best-of-2 selection,
citation verification, chat-vs-doc routing) and delegates the hard sufficiency decision to
**calibrated retrieval scores** (cross-encoder rerank scores + score-feature gate).

## v3 pipeline: score-feature escalation gate (current)

```
query
  └▶ [1] effort routing        ONE choice {no_retrieval, single_pass, multi_step} (~1-4 s)
         no_retrieval → answer directly (skip embedding search; Adaptive-RAG class A)
         single_pass → broad top-10 retrieval
         multi_step  → decompose (LLM) → per-sub-query retrieval → deduped pool (≤12)
  └▶ [2] retrieval             BM25 ‖ dense + RRF fusion → cross-encoder rerank (ONNX)
  └▶ [3] escalation gate       score-feature gate (top-1, margin, mean, above_floor)
         easy path: score ≥ θ → one LLM call → citation verification → done
         hard path: score < θ → decompose → multi-step → CRAG retry → best-of-2 → citation verification
  └▶ [4] best-of-2 (hard path) 2 candidates (thinking off/on, concurrent) → Jev selects (relative)
  └▶ [5] citation verification ONE batched call: choice per emitted [n]
         (supports/contradicts/says_nothing) + groundedness + answers-request nouls
  └▶ [6] composite score       0.4·answers_request + 0.4·citations_supported
                               + 0.2·¬contradicts_context   (code, not a model call)
```

**v3 changes from v2:**
- **Sufficiency gate removed** — replaced with score-feature escalation gate (calibrated on eval data)
- **Pointwise rerank moved to cross-encoder** — Jev rerank is now an optional testbench arm
- **Jev limited to 3 relative judgments** — effort routing, best-of-2, citations (not 7 slots)
- **Passage battery OFF by default** — miscalibrated absolute thresholds caused −20.8pp regression

Design notes:

- **Score-feature gate replaces absolute sufficiency.** The gate decides whether a question needs
  the expensive hard path *after* cheap retrieval, using calibrated signals: top-1 cross-encoder
  score, top1−top2 margin, top-k mean, count-above-floor. Threshold θ is calibrated on labeled
  eval data (gold-in-top-4) using Youden J. This fixes the v2 single-hop regression (−7.3pp → +9.8pp).
- **Effort routing replaces model routing.** The v1 `choice` between qwen3.7-plus and
  qwen3.6-plus is gone; the same single decide() call now picks the retrieval strategy.
  Validation: 9/12 on the Adaptive-RAG taxonomy, and P(no_retrieval) separates chat
  (0.76–0.96) from doc questions (≤0.17). Full-run evidence (run 0314ac0a) moved the
  shipped threshold from 0.5 to 0.9: at 0.5 one look-up policy question was misrouted
  (automatic loss) and one unanswerable question was answered from parametric knowledge
  (judged fabricated); real chat clears 0.94, so 0.9 keeps the fast path for chat while
  defaulting factual questions to retrieval.
- **Best-of-2 is a relative selector, never an absolute gate** — the planted-hallucination
  candidate still scored 0.817 in validation; ranking is safe, thresholding is not.
- **Citations auto-accept at confidence ≥ 0.8** (TypeSafe cookbook); below that they render as
  unverified, not failed.
- **One LLM per candidate, sampled concurrently** — the hard path costs one extra cloud call
  (~$0.0004) and the two candidates are generated in parallel.
- System Two also acts as a *tool* twice on the hard path: query rewrite (corrective loop) and
  question decomposition (multi-step). Both are non-streaming utility calls with tiny outputs.

### v3 knobs (`JEVRAG_*` env / `app/config.py`)

| Knob | Default | Controls |
| --- | --- | --- |
| `HYBRID_EFFORT_ROUTING` | true | effort routing on/off |
| `JEV_NO_RETRIEVAL_THRESHOLD` | 0.9 | skip retrieval only when P ≥ this |
| `JEV_MULTISTEP_SUBQUERY_K` / `JEV_MULTISTEP_MAX_POOL` | 6 / 12 | decomposition retrieval depth / rerank pool cap |
| `GATE_MODE` | `features` | escalation gate mode: `features` (score-based), `jev` (absolute), `none` |
| `GATE_SCORE_THRESHOLD` | 0.6 | threshold for features gate (calibrated on eval data) |
| `HYBRID_CORRECTIVE_RETRY` | true | CRAG retry on/off |
| `HYBRID_BEST_OF_N` | true | best-of-2 selection on/off |
| `HYBRID_CITATION_VERIFY` | true | citation verification on/off |
| `JEV_CITATION_CONFIDENCE` | 0.8 | citation auto-accept confidence |

**Testbench arms (OFF by default, configurable for experiments):**

| Knob | Default | Controls |
| --- | --- | --- |
| `HYBRID_PASSAGE_BATTERY` | **false** | passage screening battery on/off — OFF after v2 regression |
| `RERANK_MODE` | `cross` | reranker: `cross` (cross-encoder), `jev` (Jev noul), `none` |
| `JEV_INJECTION_DROP_THRESHOLD` | 0.9 | drop passage when P(injection) ≥ this |
| `JEV_CONTRADICTION_BLOCK_THRESHOLD` | 0.5 | conflict-block when P(contradiction) ≥ this |
| `JEV_EVIDENCE_DROP_THRESHOLD` | 0.1 | drop when P(evidence) < this AND relevance < 0.5 |

Every threshold follows the calibration discipline from the research: nominal thresholds miss
realized budgets, so gates are Brier-scored in the benchmark rather than trusted blindly.

**Battery status — OFF by default (evidence-based).** The v2 run
([docs/benchmark-results.md](benchmark-results.md), run 0314ac0a) measured the battery's
absolute thresholds as miscalibrated for the 0.8B stand-in: P(prompt-injection) fires at
0.91–0.98 on ordinary earnings/technical prose (25 drops, 8 gold passages lost) and
P(evidence) collapses to ~0.03 on near-duplicate KBs — over-abstention 39.5%, correctness
−20.8pp vs traditional. The finance ablation (run e98907aa,
[docs/benchmark-v2-ablation.md](benchmark-v2-ablation.md)) recovered 50% → 100% with the
battery off. Re-enable only after per-corpus threshold calibration against labeled data.

## v2 pipeline: seven decision slots (historical, 2026-09-28)

The v2 pipeline used Jev for 7 decision slots. This design caused a single-hop regression
(−7.3pp on public benchmarks) due to the absolute sufficiency gate. The v3 design replaced
this with a score-feature escalation gate and limited Jev to 3 relative judgments.

```
query
  └▶ [1] effort routing        ONE choice {no_retrieval, single_pass, multi_step} (~1-4 s)
  └▶ [2] rerank                calibrated relevance, one decide() call (unchanged from v1)
  └▶ [3] screening battery     3 nouls/passage: evidence · premise conflict · injection
         ordered thresholds → include / conflict-block / drop   (TypeSafe cookbook)
  └▶ [4] sufficiency gate      insufficient → corrective retry: rewrite query (LLM) →
         re-retrieve → re-screen (cap 1 retry; CRAG pattern)
  └▶ [5] generation            qwen3.7-plus only; multi_step or low-sufficiency →
         2 candidates (thinking off/on, concurrent), Jev best-of-2 selection
  └▶ [6] citation verification ONE batched call: choice per emitted [n]
         (supports/contradicts/says_nothing) + groundedness + answers-request nouls
  └▶ [7] composite score       0.4·answers_request + 0.4·citations_supported
                               + 0.2·¬contradicts_context   (code, not a model call)
```

The v2 knobs are still present in the code as testbench arms but are OFF by default.

## v1 decision points (superseded, kept for trace continuity)

| Step | Primitive | State | Question |
| --- | --- | --- | --- |
| Rerank | noul × N passages (one call) | `Question: {q}` | "The following passage contains information relevant to answering the question «q». Passage: «…»" |
| Sufficiency | noul (shared call) | question + kept passages (truncated) | "The passages above contain sufficient information to answer the question completely and accurately." |
| Routing | choice (shared call) | same state | options: fast synthesis model vs deep reasoning model |
| Verification | noul | question + passages + answer | "The proposed answer is fully supported by the passages above." |

Old conversations still render their v1 traces (`routing` decision records without effort).

## Validated decision patterns (experiments in `backend/scripts/`)

Measured on this sandbox (2 CPU cores, Q4_K_M):

| Pattern | Result | Latency |
| --- | --- | --- |
| Shared-state generic statements ("passage i is relevant") | **fails** — no discrimination (all ≈0.95) | — |
| Choice over passages | partial ranking, low confidence | ~1.5 s |
| **Passage text embedded in the noul instructions, one call** | **correct**: relevant 0.97 / distractor 0.02 | ~3 s for 4 passages |
| Passage-as-state, N calls | correct but N× latency | ~0.85 s/passage |
| Score (3 levels) | correct, richer signal, same cost | ~0.85 s/passage |
| Effort routing (query-as-state choice) | 9/12; no_retrieval separates chat/docs | ~1.2 s |
| Best-of-2 selection (candidates in instructions) | faithful 0.973 vs planted 0.817 | ~1.8 s |
| Citation check (3-way choice per claim) | 3/3 | one batched call |

Chosen pattern: passage text embedded in question instructions, single `decide()` call —
the state is read once and every passage gets a calibrated verdict slot.

## Cloud model (System Two — v3 uses exactly one)

| Model | Released | Price (in/out per Mtok) | Role here |
| --- | --- | --- | --- |
| qwen3.7-plus | 2026-05-31 | $0.32 / $1.28 | the single generator (direct + reasoned candidates) |
| qwen3.6-plus | 2026-03-31 | $0.50 / $3.00 | v1 reasoning route — kept in the price table for old runs; optional override for candidate B |

Sources: llm-stats.com model pages, qwen.ai blog posts, live endpoint model list (verified
2026-09-27).

## Latency profile (this sandbox, live v3 measurements 2026-09-29)

- Traditional v3 end-to-end: ~20 s (retrieval ~0.1 s + cross-encoder rerank ~0.2 s + LLM stream)
- Hybrid v3 easy path: ~20 s (same as traditional + citation verification ~2 s)
- Hybrid v3 hard path: ~41 s (adds decomposition, multi-step retrieval, CRAG retry, best-of-2)
- Hybrid v3 no_retrieval: ~23 s (one decide() call + direct LLM stream)
- Bench headline (98 questions): traditional p50 19.9 s, hybrid p50 40.9 s (2.06×)
- Knobs to trade latency vs rigor: `JEVRAG_TOP_K_RETRIEVE`, disable citation verification,
  reduce `GATE_SCORE_THRESHOLD` (more questions take the hard path)
