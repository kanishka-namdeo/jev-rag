# Beyond model routing: Jev-style decisions in a single-LLM RAG pipeline

Research note (2026-09-28). Two questions drove this pass:

1. **How else can we improve the RAG pipeline with Jev-style decision models** — beyond the
   four slots we already run (rerank, sufficiency gate, model routing, verification)?
2. **If only `qwen3.7-plus` existed** (no second model to route to), **what does the local
   Jev-style model do then?**

Grounding: two research passes over TypeSafe's official docs/cookbooks, the open Jev-style
ecosystem, and the adaptive/agentic-RAG literature (task 6-a / 6-b in `worklog.md`), plus our
own validation experiments on the local model
(`backend/scripts/experiment_single_model_routing.py`). Every external claim carries its
source URL; every local claim carries a measured number.

---

## 1. The answer to the single-model question

**The routing slot does not die — it degenerates into three decision families that the
cascade literature already validates.** With multiple models, routing answers "*which* big
model". With one model, the question becomes "**whether, how, and how many times** to invoke
it, and **which of its candidate outputs** to keep":

| Family | Decision | Published pattern | Our validation |
| --- | --- | --- | --- |
| **Whether to call** | skip retrieval entirely (chit-chat / general knowledge / parametric answer) | Adaptive-RAG's A-class routing (arxiv.org/abs/2403.14403); Mallen et al. "When Not to Trust LMs" (arxiv.org/abs/2212.10511); SKR (arxiv.org/abs/2310.05002) | choice `no_retrieval` probability separates chat (0.76–0.96) from doc questions (≤0.17) — 12/12 at a 0.2 threshold |
| **How to call (effort)** | single-pass lookup vs multi-step/decomposed retrieval; thinking-mode on/off; how many candidates to sample | Adaptive-RAG B/C classes; Hybrid-LLM's tunable difficulty routing (arxiv.org/abs/2404.14618); DeepRAG (arxiv.org/abs/2502.01142) | 3-way effort choice: **9/12 (75%)** — and the model is *correctly unconfident* on its misses (conf 0.20–0.41) |
| **Which output to keep** | best-of-N selection: generate N candidates, pick by calibrated P(grounded) | Cobbe et al. verifiers — 6B verifier's selection ≈ 30× model-size boost (arxiv.org/abs/2110.14168); Speculative RAG: +12.97% acc, −50.83% latency (arxiv.org/abs/2407.08223) | best-of-2 in ONE decide(): faithful **0.973** vs planted-hallucination **0.817** — correct winner, 1.8 s |

Plus a fourth family that never depended on model choice: **retry/corrective triggers** —
when sufficiency or verification fails, decide *what to do next* (rewrite the query and
re-retrieve, regenerate, or abstain). This is CRAG's corrective loop (arxiv.org/abs/2401.15884)
and CoVeR's verifier-call gating, which cut 62–68% of expensive-verifier calls at no accuracy
loss (arxiv.org/abs/2609.26086).

**Design consequence for Jev-RAG:** the existing `sufficiency_and_routing` decide() call
keeps its shape — the `choice` question simply changes its options from
`{default, reasoning}` (which model) to `{no_retrieval, single_pass, multi_step}`
(which retrieval strategy / effort level). Same latency budget, same single call, and the
routing decision keeps a reason to exist with exactly one cloud model.

## 2. What the research found: Jev-style value beyond routing (ranked)

TypeSafe publishes the patterns themselves (docs.typesafe.ai/patterns.md,
docs.typesafe.ai/cookbooks.md); the RAG literature independently validates the same slots.
Ranked by evidence strength for *our* pipeline:

1. **Calibrated reranking of retrieved candidates** — the strongest slot in every study.
   TypeSafe's rerank cookbook: BM25 shortlist → one Noul per query–candidate pair → top-1
   accuracy 5%→18%, top-10 38%→62% on CLERC legal queries
   (docs.typesafe.ai/cookbooks/rerank_typesafe.md). An independent "Jev in the pipeline"
   experiment: the decision-model reranker beat bge-reranker-large (NDCG@10 0.382 vs 0.331)
   and doubled multi-query fusion's lift (github.com/Raudaschl/rag-fusion —
   experiments/jev-in-the-pipeline). CRAG's 0.77B T5 evaluator beats *prompted ChatGPT* at the
   same judgment (arxiv.org/abs/2401.15884). **We already run this slot; keep it.**
2. **Per-passage screening battery before generation** — TypeSafe's classifying-RAG cookbook
   asks **4 Nouls per passage** (`is_relevant`, `contains_answer_evidence`,
   `contradicts_query_premise`, `contains_prompt_injection`) with ordered thresholds routing
   passages into include / conflict-block / drop; a planted prompt-injection was caught at
   0.99 (docs.typesafe.ai/cookbooks/classifying_rag_passages.md). This upgrades our single
   relevance-only rerank question into a safety- and conflict-aware screen — and premise
   contradictions get their own prompt block instead of silently poisoning the answer.
3. **Citation-level verification (Choice, not Noul)** — the citation-check cookbook: string-match
   first (free), then one Choice `supports/contradicts/says_nothing` per citation with
   confidence ≥ 0.8 auto-accept; caught 4/4 planted failures
   (docs.typesafe.ai/cookbooks/citation_check.md). **Our validation: 3/3** with
   confidences 0.94 / 0.84 / 0.64 in a single batched call. This is a direct upgrade path for
   our whole-answer Noul: verify each `[n]` citation the LLM actually emitted.
4. **Best-of-N candidate selection** — verifier literature (Cobbe 2110.14168; Generative
   Verifiers arxiv.org/abs/2408.15240; self-consistency arxiv.org/abs/2203.11171; Speculative
   RAG 2407.08223). **Our validation: works as a relative selector** (0.973 vs 0.817 in one
   call) — but note the tainted candidate still scored 0.817, so use it to *rank*, not to
   accept/reject at an absolute threshold.
5. **Confidence-gated escalation / selective automation** — TypeSafe's three-path pattern
   (act / confirm / escalate) with risk-scaled thresholds (docs.typesafe.ai/confidence.md,
   docs.typesafe.ai/patterns/confidence-routing.md); `jev-style eval` reports
   "automate @1%/5%/10% error budget" coverage (github.com/lawrence3699/jev-style).
   Maps to our UI: high-confidence verified answers show a green badge; medium prompts the
   user "answer may be incomplete — see trace"; low triggers the corrective loop.
6. **Composite answer-quality scoring** — weighted sum of atomic judgments in code; the docs'
   own example is literally answer gating: `0.4*answers_request + 0.4*citations_supported +
   0.2*(1-contradicts_context)` (docs.typesafe.ai/concepts/how-to-build-with-system-one.md,
   docs.typesafe.ai/patterns/composite-scoring.md). A principled replacement for our single
   "grounded %" badge.
7. **Question batching (fan-out)** — all questions over the same state are evaluated in
   parallel; batching 13 questions was 12.2× cheaper and 10.0× faster with identical answers
   (docs.typesafe.ai/cookbooks/parallel_questions.md). Our rerank already batches; the
   remaining separate calls (sufficiency+routing, verification) can absorb companion
   questions for free — e.g. effort routing + sufficiency + per-passage screens in one call.
8. **Query-transformation triggering** — multi-query/RAG-Fusion and HyDE help when retrieval
   is weak; the trigger should be a **retrieval-weakness signal** (low top reranker score /
   coverage margin), not query type alone (RAG-Fusion write-up; the Jev query-type router
   saved 22% of rewrite calls but didn't target where fusion pays). HyDE: arxiv.org/abs/2212.10496.
9. **Adaptive context budget (top-k)** — per-query retrieval depth from offline saturation
   curves: +36% F1 while reducing tokens (arxiv.org/abs/2609.13489). Compatible with our
   broad top-10 → rerank → trim design: *trim after the calibrated screen*, which also
   mitigates lost-in-the-middle ordering.
10. **Guardrails on both sides of the LLM call** — input + output hazard-Noul batteries with
    named threshold policies (docs.typesafe.ai/cookbooks/llm_guardrails.md); with a local
    KB the input-side screen doubles as prompt-injection defense for RAG.
11. **Knowledge-conflict / certainty tagging** — pre-annotate context certainty so the
    generator doesn't overtrust complex-but-uncertain sources; certainty recalibration cut
    obedience errors 25% (arxiv.org/abs/2605.06919; survey arxiv.org/abs/2403.08319).

## 3. Our validation experiments (local Jev-Style-0.8B, 2026-09-28)

Script: `backend/scripts/experiment_single_model_routing.py` (run with the backend stopped —
memory discipline; results in `worklog.md` task 6). 12 labeled queries spanning the
Adaptive-RAG taxonomy (4 no-retrieval, 4 single-pass, 4 multi-step):

| Test | Pattern | Result | Read |
| --- | --- | --- | --- |
| A1 effort routing | state = query, one choice | **9/12 (75%)** | works; misses are the corpus-awareness gap ("capital of France" → `single_pass` — the model cannot know what the KB contains), one genuinely ambiguous two-spec question, and one conditional where the model was *correctly unconfident* (conf 0.20) |
| A2 effort routing | query inside instructions | 7/12 | worse — consistent with the earlier rerank finding that the discriminating content belongs in the state for choices |
| B retrieval-need gate | standalone noul | 7/12 | perfect on chit-chat (P ≤ 0.18) but under-fires on doc questions (P 0.23–0.68). **Subsumed by A1**: the choice's `no_retrieval` probability separates cleanly (chat 0.76–0.96 vs docs ≤ 0.17) — one call gives effort level *and* a safe skip-retrieval fast-path |
| C best-of-2 selection | one call, two nouls, candidates in instructions | **correct winner** (0.973 vs 0.817) | validated as a *relative* selector; do not use as an absolute fabricate-detector threshold |
| D citation check | one call, three choices `supports/contradicts/says_nothing` | **3/3** (0.94/0.84/0.64) | validates the per-citation verification upgrade |

Latency: 0.7–1.9 s per decide() call at these small states — the effort-routing call adds
~1.2 s, not the ~10 s our large-context rerank costs.

## 4. Proposed Jev-RAG v2 pipeline (single-model design)

> **Status: IMPLEMENTED (2026-09-28)** — this proposal ships as the hybrid pipeline
> (`backend/app/rag/pipelines.py`, mirrored in `app/bench/runner.py`; design + measured
> latencies in `docs/hybrid-design.md`). Live-verified on all three effort paths; see
> `worklog.md` task 7. Every slot below maps 1:1 to code.

What we would build next, in priority order (each item names the decision slot, the call
budget, and the evidence):

```
query
  └▶ [1] effort routing + retrieval-need        ONE choice, ~1.2s  (validated A1)
         no_retrieval → answer directly (skip embedding search; Adaptive-RAG A)
         single_pass → current path
         multi_step  → decompose into sub-queries, retrieve per sub-query, merge contexts
  └▶ [2] per-passage screening battery          ONE call, rerank upgraded
         4 nouls/passage: relevant · answer_evidence · premise_contradiction · prompt_injection
         ordered thresholds → include / conflict-block / drop   (TypeSafe cookbook)
  └▶ [3] sufficiency gate                       unchanged (Brier-scored, threshold calibrated)
         insufficient → [4] corrective loop: rewrite query → re-retrieve → re-gate
         (cap at 1 retry; escalate to user on repeat failure — CRAG pattern)
  └▶ [5] generation (qwen3.7-plus only)
         multi_step or low-confidence → sample 2 candidates (thinking on/off),
         Jev best-of-2 selection by P(grounded)                 (validated C)
  └▶ [6] citation-level verification             ONE batched call, choices per emitted [n]
         supports/contradicts/says_nothing + confidence ≥ 0.8 auto-accept (validated D)
  └▶ [7] composite quality score                code-weighted: answers_request,
         citations_supported, ¬contradicts_context             (TypeSafe pattern)
```

Cost model: slots 1–2 and 6–7 add ~4–6 s of local compute per query (small states, batched)
against the current ~30 s hybrid latency — largely hidden if run while the LLM streams.
Slot 5 adds one extra cloud call (~$0.0004) only on the multi_step/low-confidence path.

## 5. What NOT to build (published negative results)

- **Decision layers that only reshuffle context behind a strong reranker** — intent-weighted
  RRF had no measurable effect in the Jev-in-the-pipeline experiment (a downstream reranker
  re-scores everything, washing out pool-boundary weights); learned context planners failed
  to beat strong hybrid retrieval+rerank on LongBench-v2 (arxiv.org/abs/2609.26976).
- **Hard evidence gates without labeled unanswerable data** — unmeasurable (same source);
  we already handle this correctly via the `outofscope` benchmark scenario.
- **Uncalibrated fixed thresholds** — nominal thresholds miss realized budgets
  (arxiv.org/abs/2607.24010); our Brier-scored sufficiency gate is the right pattern —
  extend the same calibration discipline to every new threshold.
- **Absolute accept/reject on P(grounded)** — our experiment C shows fabricated content can
  still score 0.817; rank with it, don't hard-gate on it.

## 6. Sources

TypeSafe official: docs.typesafe.ai (api, confidence, patterns, cookbooks: rerank /
classifying_rag_passages / citation_check / llm_guardrails / sde_cascade / parallel_questions /
composite-scoring), typesafe.ai/blog/introducing-system-one-models-and-jev · Open ecosystem:
github.com/TheoLeeCJ/SemIf-OpenJev, github.com/lawrence3699/jev-style,
huggingface.co/chaoliangUNSW/Jev-Style-0.8B-Decision-v3, madewithjev.com, jevwiki.ai ·
Papers: Adaptive-RAG 2403.14403 · Self-RAG 2310.11511 · CRAG 2401.15884 · FLARE 2305.06983 ·
IRCoT 2212.10509 · FrugalGPT 2305.05176 · RouteLLM 2406.18665 · Hybrid-LLM 2404.14618 ·
MoT cascades 2310.03094 · CoVeR 2609.26086 · verifiers 2110.14168 · PRMs 2305.20050 ·
Generative Verifiers 2408.15240 · self-consistency 2203.11171 · CoVe 2309.11495 ·
Speculative RAG 2407.08223 · RAGTruth 2401.00396 · HyDE 2212.10496 · RAG-Fusion
(github.com/Raudaschl/rag-fusion) · Least-to-Most 2205.10625 · Mallen 2212.10511 · SKR
2310.05002 · When-to-Retrieve 2404.19705 · LLM-Independent Adaptive RAG 2505.04253 ·
35-method benchmark 2501.12835 · Sufficient Context 2411.06037 · adaptive top-k 2609.13489 ·
ALCE 2305.14627 · AIS 2112.12870 · Chain-of-Note 2311.09210 · knowledge-conflict survey
2403.08319 · Grain-of-Salt 2605.06919 · adaptive-budget evaluation 2607.24010 ·
planner-fails-to-beat-retrieval 2609.26976. Full research transcripts: `worklog.md` tasks
6-a and 6-b.
