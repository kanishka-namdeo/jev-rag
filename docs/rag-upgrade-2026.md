# RAG Upgrade 2026: Research Synthesis, Pipeline Redesign & Jev Re-Evaluation

> Status: IMPLEMENTED + MEASURED. Results: docs/rag-upgrade-2026-results.md
> (headline run 16814bd5) and docs/testbench-results-layer1.md (Layer-1)
> Method: three parallel research agents — (R1) 2025–2026 trending RAG practice survey,
> (R2) small-model placement literature + hypothesis-testbench methodology, (A1) full
> codebase audit. Sources cited inline; project-internal evidence from
> `docs/benchmark-results.md` (runs 9d894b6c, 0314ac0a, bf05f585, 4dc6c46e, bcfdd120).

---

## 1. Where the current system stands (measured, not asserted)

| Signal | Value | Source |
|---|---|---|
| Hybrid vs trad, multi-hop subset | +18.4pp (HotpotQA +18, MuSiQue +25, 2Wiki +12.4) | runs 4dc6c46e, bcfdd120 |
| Hybrid vs trad, single-hop subset | **−7.3pp** (SQuAD −12, gate false negatives with gold top-ranked, P=0.02–0.19) | same runs |
| Hybrid latency | ~3× trad (p50 64s vs 19s) | run 4dc6c46e |
| Sufficiency-gate accuracy | 72% public / 82–92% internal; **31–37% acc, mean P 0.33–0.37 on answerable multi-hop** | run bcfdd120 |
| Retrieval saturation | TriviaQA: recall 94% both arms, hybrid = 3× latency for 0pp | run bcfdd120 |
| Lesson (confirmed 4×) | A ~0.5B zero-shot model cannot make *absolute* sufficiency judgments; only *relative* judgments are reliable | all runs |

**Diagnosis:** the hybrid pipeline asks its smallest component (the local jev-style
model) its hardest question ("is this context absolutely sufficient?") *before* the
cheapest component (retrieval) has already answered it implicitly. The single-hop
regression and the 3× latency both trace to this inversion.

## 2. What the field says (2025–2026 survey, condensed)

Adopted findings (with evidence quality noted):

1. **Gate after cheap retrieval, not before.** Adaptive-RAG's own router is ~85%
   accurate at best — routing error dwarfs our target margin; CRAG's evaluator was
   *fine-tuned*, not zero-shot; 2026 budget-aware studies find per-query pre-retrieval
   routing often loses to always-retrieve on cost-adjusted metrics. Our own TriviaQA
   run (retrieval saturated at 94% for ~0.2s) is the same conclusion from our own data.
2. **Hybrid lexical + dense + RRF fusion is the settled default.** RRF ≈ 20 lines;
   2026 hybrid-search references report NDCG@10 0.7068 (RRF) vs BM25-only baselines;
   our known failure profile (entity/lexical lookups in 2Wiki/TriviaQA with a
   multilingual-MiniLM embedder) is exactly what BM25 rescues.
3. **Cross-encoder reranking beats LLM pointwise rerank on CPU per dollar.** A 149M–278M
   cross-encoder (Hit@1 62.67→83.00% at ~150–170ms in one published comparison) dominates
   a 0.5B generative reranker for the hot path; LLM-as-reranker reproducibility work
   flags pointwise LLM reranking as the weakest and least consistent variant — which is
   precisely what `jev.rerank_chunks` does today.
4. **Contextual (title/section-prefix) chunking is nearly free.** Anthropic: top-20
   retrieval failures 5.7%→3.7% with prefix contextualization; 49% reduction when
   combined with contextual BM25 — our corpora are titled paragraphs, so the prefix
   version costs one string concat at index time.
5. **Token/call efficiency is the 2026 accuracy lever.** CompactRAG (HotpotQA 70.4%
   while *reducing* LLM calls vs IRCoT 65.2%); agentic-component ablations show
   not every loop pays — "heavy stages only on the hard path" is the pattern.
6. **Small-model calibration scales with size.** Kadavath et al.; "Mind the Confidence
   Gap"; Soudani et al. (ACL Findings 2025): no zero-shot UE method satisfies the
   RAG-setting axioms, and *simple calibrated functions on cheap features* beat raw
   model confidence. A 0.5B zero-shot absolute gate is contradicted by three
   independent lines; a *feature gate on retrieval score distributions* is supported.
7. **Citation quality should be measured (ALCE recall/precision), not just claimed.**
   Our post-hoc batched verification is architecturally current; the metric is missing.

Explicitly **skipped** (with reasons, so future maintainers don't re-litigate):
GraphRAG/LightRAG (index-time LLM cost; theme questions our benchmarks don't ask;
LightRAG's win rate shrinks under careful re-evaluation), HyDE (small-LM hallucination
hurts retrieval; our failure is lexical precision, not vocabulary mismatch), Self-RAG
(needs fine-tuned critique tokens), LLM listwise rerank (token cost, reproducibility
flags), late chunking & proposition chunking (needs token-pooling embedders / index-time
decomposition; retrieval granularity is not our binding constraint), RAPTOR (narrative
long-doc gains, our corpora are factoid), full long-context stuffing (deletes the
research premise; kept only as a calibration reference).

## 3. The upgraded architecture (v3)

Both pipelines get the modern retrieval stack; the hybrid keeps an agentic hard path.
The A/B comparison now isolates exactly the project's research question:
**does the jev-augmented layer add value on top of a 2026-baseline pipeline?**

### 3.1 Shared retrieval stack (both arms)

```
INDEX   markitdown → structure-aware split (headings, ~900/140 preserved)
        → contextual prefix ("doc title — section") into chunk text
        → dense embed (fastembed) into Chroma (cosine)
        → BM25 index over the same chunks (rebuilt lazily from Chroma contents)
QUERY   BM25 top-N ‖ dense top-N → RRF fusion (k=60)
        → cross-encoder rerank (ONNX, CPU, batched pairs) → top_k_use
```

### 3.2 Traditional v3 (= 2026 baseline)

RRF retrieval → cross-encoder rerank → top-4 → **one** cloud call → answer with
citations. No local LLM anywhere. (What the field calls the settled default.)

### 3.3 Hybrid v3 (escalation design — the gate inversion)

```
effort_routing (jev, concurrent with retrieval — only decides chat vs doc,
                P≥0.9 fast path, validated 0.76–0.96 vs ≤0.17 separation)
   ‖ retrieval (RRF) → cross-encoder rerank
EASY PATH  (gate passes: top-1 rerank score ≥ θ, calibrated on eval data)
           → one cloud call → jev citation verification → done
HARD PATH  (gate fails)
           → cloud decompose → per-sub-query RRF retrieval → rerank
           → optional passage battery → CRAG corrective retry (1)
           → best-of-2 (jev selects — relative judgment) → one cloud call
           → jev citation verification → composite quality
```

**Jev re-placement (evidence-driven):**

| Placement | v2 | v3 | Rationale |
|---|---|---|---|
| Effort routing (chat vs doc) | pre-retrieval, blocking | concurrent, no_retrieval-only | literature-supported *relative* routing; validation shows clean separation |
| Pointwise noul rerank | hot path | optional arm (testbench) | cross-encoder dominates CPU quality/$ |
| Absolute sufficiency gate | pre-generation, zero-shot | **removed** → score-feature gate | contradicted by calibration literature + our 4× confirmed failure mode |
| Best-of-2 selection | multi-step/low-suff path | hard path only | relative preference is its most defensible judgment; kept, demoted |
| Citation verification | post-answer | post-answer (kept) | anchored/lexical checks suit a 0.5B; ALCE-style metrics added |
| Passage battery (screening) | flag, default OFF | hard path option, default OFF | proven harmful (−20.8pp run 0314ac0a) without calibration |

The score-feature gate replaces the LLM judgment with cheap score signals
available *after* retrieval: top-1 cross-encoder score (primary), top1−top2 margin,
top-k mean, count-above-floor. Threshold θ is calibrated on labeled eval data
(gold-in-top-4), not hand-tuned.

## 4. Is a hypothesis-based testbench worth it? — Yes, and here is the design

The literature explicitly calls for component-wise, pre-registered evaluation
(Brehme et al. 2025 survey: feasible but under-specified in practice; 2026 practice
standardizes paired bootstrap 95% CIs + exact McNemar + BH-FDR over declared
comparisons). This project's four independent gate-failure replications are exactly
the kind of result such a harness makes rigorous — and the "how should jev-like models
be used" question is *only* answerable by isolating one placement at a time.

Two layers (cheap-first):

**Layer 1 — retrieval testbench (offline, no cloud LLM):** dense vs BM25 vs RRF
vs +cross-encoder vs +jev-rerank vs embedding swap, on all 5 public scenarios.
Metrics: recall@4, hit@1, MRR@10, nDCG@10. Runs in minutes on CPU. Doubles as
gate-threshold calibration data.

**Layer 2 — pipeline testbench (cloud LLM, resumable, reuses the shared
orchestrator):** one-factor-at-a-time ablations from the strongest base config:

| ID | Hypothesis | Arms |
|---|---|---|
| H-GATE | feature gate vs jev absolute gate vs no gate vs never/always/**oracle** bounders | gate ∈ {features, jev, none, never-retry, always-retry, oracle-retry} |
| H-RERANK | cross-encoder vs jev-logit vs no rerank | rerank ∈ {cross, jev, none} |
| H-SELECT | best-of-2 selection helps on hard path | selection ∈ {on, off} |
| H-VERIFY | citation verification flags unfaithful answers at low FP rate | verification ∈ {on, off} |
| H-HARDPATH | agentic hard path beats always-easy on multi-hop, hurts on single-hop | hardpath ∈ {on, off} |

Statistics (pre-declared): exact McNemar on discordant pairs, paired bootstrap 95% CI
(50k resamples), Wilcoxon signed-rank + rank-biserial for graded scores, BH-FDR across
the hypothesis grid. Power reality at n≈98: only ≥10–15pp effects with ≥25% discordance
reach p<0.05 — hence pooled + subset reporting, as the repo already does.

The never/always/oracle bounders answer the "is the gate worth anything" question
directly: if a gate ≈ never-retry, the stage is pure latency cost — which is the
current state on single-hop and what v3 must fix.

## 5. Implementation milestones (each pushed)

1. **M1** — this document (research synthesis + design of record).
2. **M2** — isolated modules via parallel subagents: lexical BM25+RRF, paired-stats,
   ONNX cross-encoder, structure-aware splitter.
3. **M3** — retrieval-layer integration (contextual prefix at ingestion, RRF fusion
   behind a `retrieval_mode` knob, dense fallback).
4. **M4** — cross-encoder integration at the rerank seam (`rerank_mode` knob:
   cross | jev | none).
5. **M5** — bench-runner refactor: both arms driven through `ChatService` itself,
   deleting the 230-line hand-maintained mirror (guarantees arm parity forever).
6. **M6** — pipeline v3 (gate inversion, escalation, jev re-placement, new knobs,
   `SUFFICIENCY_THRESHOLD` → real setting).
7. **M7** — testbench implementation (arm matrix + stats + offline retrieval eval +
   resumable driver + design doc).
8. **M8** — Layer-1 offline eval run + gate calibration from data.
9. **M9** — Layer-2 headline run (v3 trad vs v3 hybrid, full public suite) +
   gate-ablation subset; objective analysis.
10. **M10** — docs/README/CHANGELOG refresh; final findings report.

## 6. Objectivity contract

Every claim in the eventual results doc will carry: the run ID it came from, the
sample size, the paired statistic, and the CI. Negative results are reported with
the same prominence as positive ones (as the repo's existing results docs already
practice). If the upgraded hybrid *loses* to the upgraded traditional somewhere,
that goes in the headline table, not a footnote.
