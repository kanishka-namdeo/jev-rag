# Project status & environment report — 2026-09-30

> **Purpose of this document.** This is the complete, self-contained record of the
> engagement on this repository: what we were asked to do, the exact setup we did it
> with, what has been done and why, what the numbers say so far, and how to pick the
> work up on a more powerful machine. It is written for two audiences: the repo owner
> reviewing progress, and any engineer (human or agent) resuming the run elsewhere.
>
> Companion artifacts: [worklog.md](../worklog.md) (raw per-task log, full detail),
> [CHANGELOG.md](../CHANGELOG.md) (milestone entries), [docs/](.) (design docs and
> results), `docs/assets/testbench-hgate-partial-2026-09-30.{md,json}` (H-GATE
> interim snapshot pushed with this doc).

---

## 1. What we were supposed to be doing

The engagement brief (paraphrased from the owner's instructions, in order given):

1. **Clone and stand up the repo** — `github.com/kanishka-namdeo/jev-rag`, wired to a
   Dashscope OpenAI-compatible endpoint for cloud LLM calls (three models, used per
   role: default, reasoning, judge).
2. **Upgrade both RAG pipelines to the current best-practice methodology** — the repo
   shipped a "traditional" (single-shot retrieve→read) pipeline and a "hybrid"
   (Jev-augmented) pipeline; both were to be brought to the 2026 standard
   (hybrid retrieval, cross-encoder reranking, effort gating, hard-path
   decomposition — see §3.1).
3. **Re-evaluate where the jev model belongs** — the repo's core claim is that a
   0.8B local "Jev-Style" decision model adds value. The brief asked for an
   evidence-based placement: keep it where it measurably helps, remove it where it
   measurably hurts, and say so objectively either way.
4. **Evaluate whether a hypothesis-driven testbench is worth building** — i.e. an
   ablation harness with pre-declared hypotheses, bounder arms, and statistical
   tests, rather than ad-hoc benchmarking.
5. **Work cautiously, report objectively, push every milestone** — no silent
   failures, no cherry-picked numbers; negatives stay visible; every milestone lands
   as commits on `main`.

That brief decomposed into 14 milestones (M1–M14). M1–M11 are complete and pushed
(M11's full H-GATE run landed in commit `4e704f6`); M12–M14 are queued (§5).

### 1.1 The question M11 is currently answering

**H-GATE (hypothesis): the effort gate — deciding per-question whether to escalate
to the expensive hard path — is a net win over (a) never escalating and (b) always
escalating, and a learned gate approaches the oracle ceiling.**

Arms (identical retrieval stack, only the escalation policy differs):

| arm | escalation policy | what it isolates |
|---|---|---|
| `base` | v3 default: features gate @ threshold 0.5 | the shipped system |
| `gate-none` | never escalate | gate's value = base − gate-none |
| `always-hard` | always escalate | cost of forced hard path |
| `oracle-gate` | escalate iff gold docs not all in top-4 | headroom of a perfect gate |

Test set: 98 questions × 4 arms = 392 scored triples over five public benchmark
scenarios (SQuAD 25, HotpotQA 25, TriviaQA 16, 2WikiMultHopQA 16, MuSiQue 16),
judged by an independent LLM judge (kimi-k2.5, absolute scoring). Statistics are
pre-declared: McNemar exact vs base, paired bootstrap CIs, BH-FDR across arms.

---

## 2. Exact setup

### 2.1 Cloud LLMs (Dashscope, OpenAI-compatible)

| role | model | notes |
|---|---|---|
| default (answer generation, utility calls) | `qwen3.7-plus` | cheap+fast tier ($0.32/$1.28 per 1M in/out) |
| reasoning (hard-path decomposition, best-of-N) | `qwen3.6-plus` | ($0.50/$3.00 per 1M) |
| bench judge | `kimi-k2.5` | independent of both answer models |

- Endpoint: `https://coding-intl.dashscope.aliyuncs.com/v1` (OpenAI-compatible).
- Credentials live in `backend/.env` (git-ignored; template in
  `backend/.env.example`). **No key material is committed to the repo** — the one
  historical leak was scrubbed (worklog Task 10) and CI verifies this.
- All three models were live-probed OK on 2026-09-29 after the last environment
  rebuild (see worklog Task 2-a/2-b entries).

### 2.2 Local models (CPU, no GPU in this environment)

| component | artifact | role |
|---|---|---|
| Jev-Style 0.8B decision model | `models/jev-style/Jev-Style-0.8B-Decision-v3-Q4_K_M.gguf` (529,296,864 bytes, from `chaoliangUNSW/Jev-Style-0.8B-Decision-v3-GGUF`) | routing/selection/verification decisions |
| `jev-score` scorer binary | `models/jev-style/build/jev-score` (llama.cpp build, shallow clone at `00af635`) | fast sufficiency scoring, batched, n-ctx 8192 |
| dense embedder | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (ONNX via fastembed) | dense retrieval + query embedding |
| cross-encoder reranker | `Xenova/ms-marco-MiniLM-L-6-v2` (~22M params, ONNX) | v3 rerank stage |

### 2.3 Software stack

- Backend: Python 3.12.14 venv (`backend/.venv`), FastAPI 0.141.1, chromadb 1.5.9,
  fastembed 0.8.1, sqlalchemy 2.1.1, `jev-style` 0.3.0 (pip). 121 backend tests.
- Frontend: Next.js 16 + TypeScript (repo root `src/`), served by the platform dev
  server; not involved in benchmarking.
- Storage: SQLite (`backend/data/app.db`) for runs/results; chroma + BM25 indices
  under `backend/data/` (volatile in this environment — §2.4).
- Everything is reproducible from the repo:
  `scripts/setup_backend.sh` (venv+deps via uv), `scripts/setup_local_models.sh`
  (GGUF download + llama.cpp build, idempotent/resumable), `backend/.env.example`.
  Full fresh-machine steps: [docs/setup.md](setup.md).

### 2.4 The execution environment (why things are slow here)

This engagement runs in a **hosted sandbox with severe operational constraints**,
which shaped the entire working method. They are the honest context for every
timing number in this report:

- **4 GB RAM total.** One runner process (embedder + chroma + cross-encoder +
  jev-score child) peaks at ~1.8 GB; two concurrent runners OOM-kill each other at
  startup. → benchmark execution is strictly single-process.
- **A process reaper.** Long-lived processes are killed at unpredictable intervals
  (observed: 11 s to ~17 min). Backgrounding (`nohup`, `setsid`, `&`) does not
  survive reliably either. → only **chained foreground windows** are safe: the
  runner was built with `--window-minutes` + per-triple atomic commits, so each
  window exits gracefully (or is killed) and the next invocation resumes exactly
  where the previous stopped (`--resume RUN_ID`). No work is lost except the
  in-flight triple.
- **Sandbox state resets** (5 times this engagement): `backend/.venv`, `models/`,
  `vendor/`, `backend/data/` (incl. the run database) are wiped; source, git, and
  `worklog.md` persist. → the two setup scripts rebuild the environment in ~5 min;
  in-flight benchmark runs restart from zero (this cost the first H-GATE attempt,
  42/98 questions, on 2026-09-29).
- **10-minute tool-call ceiling.** Every window must fit inside one foreground
  tool call (windows are sized at 8.2 min + ~1 min startup ≈ 15–18% overhead).

**Implication:** the same 392-triple run on a normal workstation — single
uninterrupted process, no OOM, no reaper, no reset — is roughly **1.3–1.5× faster
serially** (window overhead removed), and can be parallelized further (e.g. one
runner per scenario on separate data dirs, RAM permitting) for up to ~5× on a
16 GB+ box. §6 has the exact commands.

---

## 3. What has been done, and why — milestone by milestone

All M-milestones below are pushed to `origin/main`. Commit IDs in parentheses.
Raw detail per task: [worklog.md](../worklog.md).

### 3.1 M1–M6 — the v3 upgrade (both pipelines)

- **M1 (b272649) Research.** Three parallel research agents surveyed 2026 RAG
  practice: hybrid sparse+dense retrieval with reciprocal-rank fusion, cross-encoder
  reranking over a candidate pool, adaptive-effort gating (cheap path first,
  escalate when signals say the question is hard), multi-step decomposition for
  multi-hop, answer verification. Delivered as `docs/rag-upgrade-2026.md`.
- **M2 (55f33de) Build.** Four parallel implementation subagents built isolated
  modules behind config flags — nothing shipped before it was measured.
- **M3 (227c495) HybridSearch.** BM25 (pure-python rank_bm25, doc-scoped lazy
  index) fused with dense via RRF (k=60), context-aware chunk prefixes preserved.
  Why: fixes the dense-only failure mode where exact term matches (IDs, names)
  rank below semantic paraphrases.
- **M4 (089e3f3) Cross-encoder rerank, everywhere.** `rerank_mode = cross|jev|none`
  selectable in BOTH pipelines. The 22M ONNX cross-encoder replaced jev as the
  default hot-path reranker after measurement (M8: jev rerank was the weakest
  reranker, −3.5pp vs no rerank; cross-encoder is the standard, and it is ~30×
  smaller than the LLM-judge alternative).
- **M5 (48cc0b1) Integration cleanup** before new features landed: dead v2 code
  removed single-site, both pipelines share one retriever stack.
- **M6 (1b4d827) Hybrid v3 orchestration.** Effort routing runs concurrently with
  retrieval (latency-hiding), the features gate decides escalation, hard path =
  multi-step sub-query decomposition + best-of-N + citation verification +
  corrective retry. Jev decisions kept for relative judgments (route selection,
  answer selection, verification) — see §3.2.

### 3.2 M1-bis — the jev re-placement (evidence-based)

The brief explicitly asked: *re-assess where the jev model sits*. Answer, from the
Layer-1 + Layer-2 measurements (M8/M9), and reflected in v3's architecture:

| jev role | verdict | evidence |
|---|---|---|
| absolute sufficiency ("is this context enough?") | **removed** | gate calibration acc .59 at its best threshold; replaced by the features gate: acc .898, Brier .103 (M9) |
| hot-path pointwise rerank | **removed** | weakest reranker measured, −3.5pp recall@4 vs no rerank (M8 Layer-1) |
| relative judgments: routing, answer selection (best-of-N), verification | **kept** | consistent, and the decision trace (calibrated probabilities in the UI trace panel) is a product feature |

This is the repo's honest self-correction: the 0.8B model still earns its place,
just not where the original design put it.

### 3.3 M7 (23f3012) — the testbench: built because the brief asked whether it's worth it

`docs/testbench-design.md` pre-declares the hypotheses and statistics BEFORE any
run: H-GATE (§1.1), H-RERANK (cross vs jev vs none, e2e), H-JUDGE (label
distillation). Two layers:

- **Layer-1** — offline retrieval grid (no cloud calls, minutes): isolates
  retrieval/rerank quality with hit@1/MRR on gold chunks. Ran the full matrix
  (98Q × 7 retrieval arms, M8).
- **Layer-2** — resumable end-to-end ablations with bounder arms (oracle-gate,
  always-hard), an independent judge, McNemar exact + paired bootstrap + BH-FDR.
  The runner (`backend/scripts/run_testbench.py`) was engineered for THIS
  environment: per-triple atomic commits, window budgets, chained resume — it
  survived 5 sandbox resets and dozens of process kills with zero data loss
  (the one loss was the volatile DB itself, on reset).

Verdict on "does a hypothesis-driven testbench make sense?": **yes, and it is now
the repo's standard evidence format** — every claim above has a run ID behind it.

### 3.4 M8 (e3e92a0) — Layer-1 results (98Q × 7 retrieval arms)

v3 default configuration confirmed best precision (hit@1 .918, MRR .942). Key
negatives kept visible: BM25-alone −6.2pp (p=0.001) — fusion justified; jev rerank
−3.5pp — removed from hot path; bge embedder swap REJECTED (−1.9pp, n.s.).
Gate calibration offline: theta*=0.987 acc .59 → shipped threshold 0.5 with the
features gate instead (escalation ~15–17% on hard scenarios).

### 3.5 M9 (3eaf3b6) — the headline v2→v3 run (16814bd5, 98Q, 0 errors, ~$0.31)

| metric | v2 | v3 | verdict |
|---|---|---|---|
| pooled correctness | — | **+5.1pp** | p=0.065 (borderline, reported as such) |
| single-hop correctness | −7.3pp vs baseline | **+9.8pp** | SIGNIFICANT (Wilcoxon p=.048, CI [+2.4, +19.5]) — the v2 single-hop regression is fixed and inverted |
| multi-hop | v2 edge | +1.8pp | n.s. — the stronger v3 baseline ate the v2 win; reported honestly |
| over-abstention | 35.7% | **25.5%** | fewer false "I can't answer" |
| latency vs baseline | ~3× | **2.06×** | |
| cost per 98Q suite | $0.165 | **$0.148** | hybrid is CHEAPER |
| features-gate quality | acc .72 / Brier .38 | **acc .898 / Brier .103** | |

Also: 6/10 gate escalations recovered otherwise-wrong answers; the other 4 were
honest abstentions on unanswerable questions. The prior 20Q×3 H-GATE pilot
(6b58fc40) pointed the right direction (base .70 > gate-none .65 > always-hard
.60 at 2.6× latency) but was underpowered — which is exactly why the current
M11 full-power run exists.

### 3.6 M10 — reporting pass

README rewritten around v3 (architecture mermaid, results-with-receipts table, v2
kept as history with its own numbers), CHANGELOG milestone entries, benchmark
docs, backend restarted on v3 config, 121/121 tests green.

### 3.7 This session (post-4th/5th reset) — environment + M11 complete

Commits pushed this session family: `aa75203` (gate-calibration metrics: ECE /
Brier / FN / FP in the analyzer), `5eb65d4` (resume contract fix: bare `--resume`
adopts the run's recorded arms/scenarios instead of silently widening them),
`0f6ec7e` (skip-if-ready scenario ingestion — 3.5 min/4-arm question → seconds on
resume), `71f73a3` (flock-guarded cron window wrapper, for hosts with cron).

M11 H-GATE full-power run: **completed** on the owner's Windows workstation
under WSL2 Ubuntu-24.04 (RTX 2070 Super) as **5 parallel runners, one per
scenario on separate `JEVRAG_DATA_DIR`s** (§6 scale-up runbook, the authorized
"5× wall-clock" pattern). 392/392 unique triples (391 scored + 1 documented
Dashscope `APITimeoutError` on musique `mq14/oracle-gate`, kept visible per the
objectivity contract). Per-scenario DBs merged into one canonical
`backend/data_merged/app.db` by `backend/scripts/_merge_par_run.py` → unified
run `67a1dc06-a3bd-4bf1-8f25-092cd5db3eff`. Full readout in §4.2 (full power)
and the historical 192-triple snapshot is retained as §4.2bis. Commit `4e704f6`
pushed the results doc + merge script + DOX ownership rows.

---

## 4. Results so far

### 4.1 Completed (see §3.4–3.5 for full context)

- v3 stack beats v2 on every headline metric (M9, run 16814bd5), with the
  single-hop regression fixed-and-inverted at significance; the pooled gain
  (+5.1pp) is reported as borderline, not oversold.
- jev re-placed on measurement (§3.2); testbench adopted as the standard evidence
  format (§3.3).

### 4.2 M11 H-GATE — full power (merged run 67a1dc06, 392/392 triples, 1 documented error, complete)

Full readout (98 questions × 4 arms, all five public scenarios, independent
judge kimi-k2.5, absolute scoring) in [testbench-results-hgate.md](testbench-results-hgate.md)
and its JSON twin `testbench-results-hgate.json`. Judge-scored correctness by arm:

| arm | corr | Δ vs base | McNemar p | FDR q | escalate | p50 latency |
|---|---|---|---|---|---|---|
| base (v3, gate @0.5) | **0.6735** | — | — | — | 19.4% | 20.8 s |
| always-hard | 0.6735 | ±0.0 | 1.000 | 1.000 | 100% | **73.2 s (3.5×)** |
| oracle-gate | 0.6392 | −3.4pp | 0.629 | 0.944 | 31.6% | 20.8 s |
| gate-none | 0.6276 | −4.6pp | 0.424 | 0.944 | 0% | 18.5 s |

Subsets: single-hop (n=41) base 0.890 / gate-none 0.829 / always-hard 0.854 /
oracle 0.793; multi-hop (n=57) base 0.518 / gate-none 0.483 / always-hard 0.544
/ oracle 0.527. Gate calibration (features gate vs ground-truth
answerability): acc 0.857, Brier 0.117, ECE 0.16, FN-on-answerable 0.143.

**Final reading (n is full power — this replaces the interim §4.2 interim
table and the `be7b62ea` 192-triple snapshot in `docs/assets/`):**

1. **H-GATE is NOT confirmed at full power.** The gate's marginal value over
   never-escalating (base − gate-none = +4.6pp) is **not significant**
   (McNemar p 0.424, FDR q 0.944). The direction is the same as the pilot and
   the M9 6/10-recovery observation, but 98 questions is not enough power to
   call it — reported honestly, not oversold.
2. **Forced escalation is a pure cost, confirmed.** always-hard ties base on
   accuracy (±0.0, p 1.0) at **3.5× median latency** and +17.4% cost per
   question ($0.188 vs $0.161). The hard path's per-question benefit is eaten
   by its multi-step token burn when applied unconditionally.
3. **The oracle gate UNDERCUTS base** (−3.4pp, n.s.). This inverts the
   interim expectation that "oracle ≥ base": on the full set a perfect
   escalate-iff-gold-not-in-top-4 policy is *worse* than the learned
   features gate, because forcing the hard path on questions where the cheap
   path already succeeded hurts more than it helps (see M12 for the
   rerank-regression interaction on MuSiQue).
4. **One documented error** (objectivity contract): `musique/mq14/oracle-gate`
   hit a transient Dashscope `APITimeoutError` and is recorded as an error row
   in the merged DB (392 triples, 391 scored + 1 error). It was *not*
   re-run or dropped — the negative stays visible. Base/gate-none/always-hard
   on mq14 all scored, so the arm-level table above is computed on the full
   98-question denominator with that one cell excluded from the oracle-gate
   column only.

### 4.2bis M11 H-GATE — interim (run be7b62ea, 192/392 triples, historical, superseded)

Judge-scored correctness by arm (n = 48 questions completed; McNemar exact vs base):

| arm | corr | Δ vs base | McNemar p | escalate | p50 latency |
|---|---|---|---|---|---|
| base (v3, gate @0.5) | **0.865** | — | — | 14.6% | 36.0 s |
| gate-none | 0.802 | −6.2pp | 0.375 (n.s.) | 0% | 36.4 s |
| always-hard | 0.833 | −3.1pp | 0.688 (n.s.) | 100% | **101.5 s (2.8×)** |
| oracle-gate | 0.865 | ±0.0 | 1.000 | 14.6% | 38.9 s |

Subsets: single-hop (n=25) base 0.90 / gate-none 0.86 / always-hard 0.88;
multi-hop (n=23) base 0.826 / gate-none 0.739 / always-hard 0.783.
Gate calibration (features-gate score vs ground-truth answerability):
acc 0.875, Brier 0.123, ECE 0.157, FN-on-answerable 0.125.

**Interim reading (superseded by §4.2 above — kept only as the historical
192-triple snapshot from the sandbox):**

1. The v3 gate is directionally earning its keep: base > gate-none by +6.2pp at
   equal latency (the gate itself is nearly free; escalations fire ~15% of the
   time). Consistent with the 20Q pilot and the M9 6/10-escalation-recovery
   observation.
2. Forced escalation (always-hard) is a pure loss on this mix: −3.1pp accuracy at
   2.8× median latency. The hard path helps only when the gate (or the oracle)
   says it is needed — which is precisely the design argument.
3. The oracle ceiling currently equals base (0.865): on the questions completed
   so far, a perfect gate would not have added accuracy over the learned gate.
   The interesting test is whether the remaining scenarios (TriviaQA, 2Wiki,
   MuSiQue — the hardest multi-hop set) open a gap between base and oracle.
   **This gap did NOT open — the full run found the oracle *below* base (see
   §4.2 point 3).**
4. Full-run verdicts now land in `docs/testbench-results-hgate.md` and the
   CHANGELOG M11 entry (§4.2 above is the readout).

### 4.3 Known negatives on record (not hidden)

- Rerank hurts MuSiQue recall (.635 → .557) — M12 exists to resolve this.
- 2WikiMultiHopQA is hard for every arm (~.28 in Layer-1 retrieval) — reported,
  not tuned away.
- Pooled v2→v3 gain is borderline, not significant at n=98 (multi-hop edge
  compressed by the stronger baseline).
- The features-gate's top-1 signal is weak for gold-in-top-4 questions (M8).

---

## 5. Remaining work (queued, in order)

| milestone | what | why |
|---|---|---|
| ~~M11~~ ✅ **done** (full 392-triple run complete, analyzed, results committed to [testbench-results-hgate.md](testbench-results-hgate.md)) | — | gate verdict: marginal value NOT confirmed at full power (base − gate-none = +4.6pp, n.s.); forced escalation confirmed pure cost; oracle undercuts base |
| **M12** | H-RERANK e2e ablation: cross vs jev vs none on the multi-hop scenarios; resolve the MuSiQue rerank regression | rerank is on the hot path; the regression is a real cost if it survives e2e |
| **M13** | "Codifying the judge": distill the cloud judge's binary verdicts into the local features+jev-score gate; report Brier/ECE delta | the judge labels are already persisted per-triple (jev_decisions) — a free calibration set |
| **M14** | final objective report: consolidate M11–M13 into the README results table + CHANGELOG; push | closes the engagement brief |

---

## 6. Running this on a powerful system (resume / scale-up runbook)

The repo is deliberately portable — this is the exact fresh-machine sequence:

```bash
git clone https://github.com/kanishka-namdeo/jev-rag.git && cd jev-rag

# 1. environment (~5 min; both scripts are idempotent + resumable)
bash scripts/setup_backend.sh          # uv venv + requirements (Python 3.12)
bash scripts/setup_local_models.sh      # GGUF download + llama.cpp jev-score build

# 2. credentials
cp backend/.env.example backend/.env    # then fill JEVRAG_DASHSCOPE_API_KEY etc.

# 3. verify (all should print ok/True)
cd backend && .venv/bin/python -c "
from app.config import get_settings
from app.llm.dashscope import DashscopeLLM
from app.llm.jev_engine import JevEngine
from app.rag.retriever import Embedder
from app.rag.crossenc import CrossEncoderReranker
s = get_settings()
print(DashscopeLLM(s).complete(model=s.llm_model_default, system='prober', user='say ok', max_tokens=8)[0])
print('jev', JevEngine(s).load(), 'embedder', Embedder(s).load(), 'crossenc', CrossEncoderReranker().load())
"
```

**M11 from scratch (what is running here):**

```bash
cd backend && .venv/bin/python scripts/run_testbench.py \
  --arms base,gate-none,always-hard,oracle-gate \
  --scenarios squad,hotpotqa,triviaqa,wiki2,musique \
  --label "H-GATE full power" \
  --window-minutes 100000      # unlimited: single uninterrupted run on real iron
```

**M11 resuming an interrupted run** (the runner commits each scored triple
atomically — resume is exact):

```bash
cd backend && .venv/bin/python scripts/run_testbench.py \
  --resume <RUN_ID> --window-minutes 100000
```

**Analysis** (any time, also mid-run for interim readouts):

```bash
cd backend && .venv/bin/python scripts/analyze_testbench.py <RUN_ID> --out ../docs/testbench-results-hgate.md
```

Scaling notes for real hardware:
- Per-triple latency is dominated by cloud LLM round-trips (answer + judge) and
  the hard path's multi-step chains — a faster CPU mainly removes this sandbox's
  *operational* overhead (windows, OOM, resets), i.e. the ~1.3–1.5× serial win.
- RAM ≥ 16 GB enables the real speedup: one runner per scenario on separate
  `JEVRAG_DATA_DIR`s (5 processes ≈ up to 5× wall-clock), each still cheap on
  Dashscope. Merge analyses by run ID per scenario.
- Cost is model-side, not machine-side: the full 392-triple H-GATE run costs
  roughly $0.30–0.60 in Dashscope tokens (M9's 98Q×2-arm suite was $0.31; the
  4-arm run scales it).
- The committed interim artifacts in `docs/assets/` (JSON snapshot + analysis)
  mean the 192 triples already scored here do NOT need to be re-run on the new
  machine if you keep the same SQLite DB — or can simply serve as a consistency
  cross-check if you re-run from scratch (questions, sampling seeds and judge
  are all deterministic given the same models).

---

## 7. Where everything lives

| artifact | path |
|---|---|
| raw task log (per-task, append-only) | [worklog.md](../worklog.md) |
| milestone entries | [CHANGELOG.md](../CHANGELOG.md) |
| v3 design + research | [docs/rag-upgrade-2026.md](rag-upgrade-2026.md), [docs/rag-upgrade-2026-results.md](rag-upgrade-2026-results.md) |
| testbench design (pre-declared hypotheses) | [docs/testbench-design.md](testbench-design.md) |
| Layer-1 results | [docs/testbench-results-layer1.md](testbench-results-layer1.md) |
| public-benchmark results (v2→v3 headline) | [docs/benchmark-results.md](benchmark-results.md) |
| H-GATE interim snapshot (this push) | `docs/assets/testbench-hgate-partial-2026-09-30.{md,json}` |
| runner / analyzer / export scripts | `backend/scripts/` |
| fresh-machine setup | [docs/setup.md](setup.md) |

---

## 8. Resumption record — 2026-09-30 (owner's Windows machine, WSL2)

The owner picked up the run on a Windows workstation with WSL2
(`Ubuntu-24.04`) and an RTX 2070 Super. Key differences from the sandbox:

- **No process reaper, no sandbox resets, no 4 GB OOM wall** — a single
  uninterrupted foreground/`setsid`-detached process is safe, so the
  `--window-minutes 8` chained-window protocol is no longer required.
- **ONNX Runtime CUDA provider is unavailable in WSL2** (documented
  [setup-gpu.md](setup-gpu.md)): `CUDA failure 100: no CUDA-capable device
  is detected`. The embedder and cross-encoder gracefully fall back to CPU
  (verified via the load smoke test). `jev-score` (llama.cpp) is a Linux
  ELF binary and runs on CPU in WSL2.
- The sandbox-era 192-triple run state (`be7b62ea`) was **not portable** —
  it lived in the sandbox's `backend/data/app.db`, which is wiped on every
  sandbox reset and is not committed. The committed interim snapshot
  ([testbench-hgate-partial-2026-09-30](assets/testbench-hgate-partial-2026-09-30.md))
  is a record only, not a resume point.

**Fresh run on this machine:** the first serial attempt
(`b5203ed0`, 72 squad triples) was superseded by a **5-way parallel run**
(§6 runbook, one runner per scenario on separate `JEVRAG_DATA_DIR`s),
launched 2026-09-30 14:35 local via `setsid nohup` inside `Ubuntu-24.04`.
Arms/scenarios identical to the original H-GATE spec:
`base,gate-none,always-hard,oracle-gate` ×
`squad,hotpotqa,triviaqa,wiki2,musique` (392 triples total).
**COMPLETED ~16:20 local (~2 h wall-clock).** All 5 scenarios `completed`,
0 pipeline errors; 1 documented transient Dashscope `APITimeoutError`
(musique `mq14/oracle-gate`), kept visible per the objectivity contract.

The 5 per-scenario DBs were merged into one canonical
`backend/data_merged/app.db` by `backend/scripts/_merge_par_run.py`
(dedupe by scenario/question/arm, keep most-recent non-error row; picks
each scenario's *completed* run so the later in-flight retry run cannot
win the tie-break) → unified run `67a1dc06-a3bd-4bf1-8f25-092cd5db3eff`
(392 rows, 391 scored + 1 error). Analysis:
`JEVRAG_DATA_DIR=backend/data_merged .venv/bin/python scripts/analyze_testbench.py 67a1dc06-… --out ../docs/testbench-results-hgate.md`
→ [testbench-results-hgate.md](testbench-results-hgate.md).

**The resumption is now complete** — the §4.2 full-run readout above
replaces this section's "in flight" framing. §8's resume/analyze commands
are retained for reference only.

**How to check progress / resume:**

```bash
# from d:\test_jev\jev-rag (Windows PowerShell), one-liner:
wsl -d Ubuntu-24.04 -- bash -c "bash /mnt/d/test_jev/jev-rag/scripts/_wsl_status.sh"

# or inside WSL:
cd /mnt/d/test_jev/jev-rag && bash scripts/_wsl_status.sh

# if the process died but the DB has partial triples, resume:
cd /mnt/d/test_jev/jev-rag/backend && \
  .venv/bin/python scripts/run_testbench.py --resume b5203ed0-51fe-4dfa-b51a-201208340002 \
  --window-minutes 60000
```

**On completion:** run the analyzer and write the results doc:

```bash
cd /mnt/d/test_jev/jev-rag/backend && \
  .venv/bin/python scripts/analyze_testbench.py b5203ed0-51fe-4dfa-b51a-201208340002 \
  --out ../docs/testbench-results-hgate.md
```

Then replace the §4.2 interim section with the full-run readout, add the
M11 CHANGELOG entry, and push.

