# Changelog

Milestone history for Jev-RAG. Each entry links to the commit that delivered it.
Dates are YYYY-MM-DD (commit date). Format is loosely inspired by
[Keep a Changelog](https://keepachangelog.com/), grouped by project phase.

## 2026-09-30 — M11 H-GATE full-power run complete (parallel x5 on WSL2)

The H-GATE hypothesis (§1.1 of
[docs/project-status-2026-09-30.md](docs/project-status-2026-09-30.md)) is now
answered at full power: **98 questions × 4 arms = 392 scored triples** across
all five public scenarios (SQuAD 100, HotpotQA 100, TriviaQA 64, 2WikiMultHopQA
64, MuSiQue 64), judged by the independent `kimi-k2.5` LLM judge.

**Execution (the §6 scale-up runbook, in practice):** the sandbox-era 192-triple
state was not portable (its DB is wiped on every reset), so the run started
fresh on the owner's Windows workstation under **WSL2 Ubuntu-24.04 + RTX 2070
Super**. It was run as **5 parallel runners, one per scenario, each on its own
`JEVRAG_DATA_DIR`** — the §6-authorized "one runner per scenario on separate
data dirs (~5× wall-clock)" pattern. Each worker is fully isolated (its own
SQLite + Chroma + ONNX cache + `jev-score` subprocess); the 5 DBs were then
merged into one canonical `backend/data_merged/app.db` by a new
`backend/scripts/_merge_par_run.py` (dedupe by scenario/question/arm; picks each
scenario's *completed* run so a later in-flight retry cannot win the tie-break),
producing unified run `67a1dc06` (392 rows).

- **New script**: [`backend/scripts/_merge_par_run.py`](backend/scripts/_merge_par_run.py)
  — merge the per-scenario parallel-run DBs into one analyzer-compatible DB.
  Repo-committable; emits the unified run id + the exact `JEVRAG_DATA_DIR=…`
  analyzer command to run next.
- **Results**: [docs/testbench-results-hgate.md](docs/testbench-results-hgate.md)
  (+ `.json` twin) — the full-run readout.

**Verdict (objective, negatives kept visible):**
- **H-GATE not confirmed at full power.** Gate value (base − gate-none = +4.6pp)
  is the right direction but **not significant** (McNemar p 0.424, FDR q 0.944)
  at n=98. The pilot and M9 pointed this way; full power is underpowered to
  call it.
- **Forced escalation confirmed a pure cost**: always-hard ties base (±0.0,
  p 1.0) at **3.5× median latency** and +17% per-question cost.
- **Oracle gate undercuts base** (−3.4pp, n.s.) — inverting the interim
  "oracle ≥ base" expectation. The hard path *hurts* when applied to questions
  the cheap path already got right; the MuSiQue rerank-regression interaction is
  the likely cause (queued for M12).
- **One documented error** (objectivity contract): `musique/mq14/oracle-gate`
  hit a transient Dashscope `APITimeoutError` and is recorded as an error row
  (391 scored + 1 error). It was neither re-run nor dropped.

Why: the gate was the last unvalidated v3 component at full power; running it
on real hardware (parallel, no sandbox reaper/OOM wall) was the §6-resume
path and completed in ~2 h instead of the ~5 h the serial run would have
taken. M11 is now closed; M12/M13/M14 remain queued (§5 of the status report).

## 2026-09-30 — Session state report + H-GATE interim results pushed

The engagement brief (upgrade both pipelines, re-place jev on evidence, evaluate
a hypothesis testbench, objective reporting, milestone pushes) is now fully
documented in a single self-contained report —
[docs/project-status-2026-09-30.md](docs/project-status-2026-09-30.md) — covering
mission, exact setup (models/roles/endpoint, local artifacts, versions), the
sandbox execution protocol (OOM/reaper/window constraints and how the runner was
engineered around them), the full M1–M11 narrative with the reasoning behind each
decision, and a resume-on-real-iron runbook.

Pushed alongside the report:

- **H-GATE interim snapshot** (run `be7b62ea`, 192/392 triples, 0 errors):
  `docs/assets/testbench-hgate-partial-2026-09-30.md` (analyzer output) and
  `.json` (all 192 scored rows, machine-readable). Interim: base .865 >
  always-hard .833 (2.8x latency) > gate-none .802; oracle-gate = base
  (n=48 — not final; TriviaQA/2Wiki/MuSiQue still running).
- **`backend/scripts/dump_partial_run.py`**: repo-committable JSON export of a
  running testbench run (the completed-run exporter refuses in-flight runs).
- README: status report + testbench-design rows in the doc tour, and the
  2026-09-30 milestone row (testbench hardening commits + H-GATE launch).

Why: the run had to restart from zero after the sandbox's 5th state reset wiped
the run database; committing the interim rows makes the scored work portable and
lets a more powerful machine resume or re-verify without re-paying for what is
already measured.

## 2026-09-29 — Repo beautification: user-friendly README + community files

The README was accurate but text-heavy (302 lines, dense prose walls). Following
published README best practices (visual-first hierarchy, collapsible depth,
one-glance answers), the repo surface was restructured for visitors:

- **README rewritten around the visitor's path**: centered banner → one-line
  pitch → badges (added PRs Welcome) → headline stat strip → hero screenshot →
  emoji-anchored section nav. Screenshots moved to the top (show, don't tell);
  interpretation prose, full config table, milestones, and agent/DOX notes now
  live in `<details>` collapsibles — the visible surface is scannable in one
  viewport per section, while every number, caveat, and negative result is
  preserved (objectivity contract intact: losses stay visible, full readings
  one click away).
- **New community files**: [CONTRIBUTING.md](CONTRIBUTING.md) (60-second dev
  setup, tests/lint bar, what a good PR looks like — measured claims in both
  directions, no secrets), [SECURITY.md](SECURITY.md) (private disclosure
  policy, leaked-credential handling, local-only scope note).
- **Issue & PR templates**: structured bug report (pipeline picker, trace
  panel, preflight checklist), feature request (failure-mode framing, local-first
  scope check), issue-template contact links (setup guide, benchmarking docs,
  security), and a PR checklist template with the safety boxes.
- README now links all of the above; broken-link and anchor audit passed
  (every referenced file, image, and doc anchor exists).

## 2026-09-28 — Portability hardening + fresh-system setup guide

Setting the repo up on **another machine** is now a documented, verified path —
and the code was proactively fixed to make it true, not just claimed:

- **[docs/setup.md](docs/setup.md)** — the binding fresh-system guide: hardware/OS/software
  requirements, the five-step setup path, the path-resolution contract, verification
  (health, endpoint probe, tests, lint, e2e smoke), day-2 operations, benchmark
  reproduction and a troubleshooting table. Linked from the README quickstart and the
  docs index; every doc that touches setup cross-references it.
- **Repo-root path anchoring** (`backend/app/config.py`): relative paths in
  `backend/.env` and `.env` discovery now resolve against the repo root instead of the
  process CWD — uvicorn, scripts and diagnostics behave identically no matter where
  they're launched from. Verified from three different working directories.
- **Machine-independent scripts**: `setup_backend.sh`, `setup_local_models.sh`,
  `backend_service.sh`, `init-fullstack-reference.sh` and the ensure-backend route no
  longer hardcode the original sandbox path; file-size checks use `python3` (GNU-only
  `stat -c%s` breaks macOS); the cmake pip-bootstrap honors `JEVRAG_PIP_INDEX_URL` /
  `UV_INDEX_URL` mirror overrides instead of baking one in.
- **Secrets hygiene**: the endpoint probe (`scripts/probe_public_gateway.sh`) now reads
  credentials from `backend/.env`/env instead of a hardcoded API key; the stale tracked
  root `.env` was removed; build noise (`.next/`, `dev.log`) untracked from git.
- **Fixes**: corrupted CI push trigger (`branches: ain]` → `[main]` — pushes to main now
  run CI); `analyze_bench_run.py --db` now actually reads the DB it's pointed at
  (previously parsed but ignored, with a stale default path).
- **Validation**: the fixed setup path was executed end-to-end on a wiped environment
  (venv rebuild → model download + llama.cpp build → backend boot from an outside CWD,
  healthy in 15 s); 35/35 backend tests and frontend lint green.

## 2026-09-28 — Public benchmarks wave 2: TriviaQA + 2WikiMultiHopQA + MuSiQue

Run `bcfdd120`: 48 further seeded questions (16 per benchmark) through the same
audited two-arm protocol and independent judge (kimi-k2.5, self-test 8/8),
extending the public suite from two to **five canonical benchmarks (98
questions)**:

- **MuSiQue-Ans val (compositional multi-hop): hybrid 37.5% vs traditional
  12.5% (+25pp)** — the traditional arm collapses under adversarial
  topically-related distractors (13/16 abstentions); the hybrid's multistep
  subquery decomposition lifts recall@4 +13pp (47→60%) and retry converts
  abstentions into answers.
- **2WikiMultiHopQA val (structured multi-hop): hybrid 56.2% vs 43.8%
  (+12.4pp)**, recall@4 +9.4pp — same mechanism as HotpotQA (+18pp, wave 1),
  now shown on a second multi-hop benchmark with Wikidata-triple evidence.
- **TriviaQA rc.wikipedia val (single-hop): a dead tie (75.0% vs 75.0%)** —
  retrieval saturated for both arms (94% recall@4); the decision layer adds
  latency (3×) and nothing else. The JeV rerank even trades −3.1pp recall on
  saturated single-hop retrieval.
- **Pooled wave 2: +12.5pp (56.2% vs 43.8%), n.s.** (McNemar p=0.21, Wilcoxon
  p=0.35); pairwise 14W/3L/31T (61.5%). Across all five public benchmarks:
  **+7.6pp (66.8% vs 59.2%)**; multi-hop subset (57 Q) **+18.4pp**, single-hop
  subset (41 Q) **−7.3pp** — hybrid is a scattered-evidence specialist, two
  for two on single-hop neutrality/losses.
- **Gate miscalibration, 4th independent confirmation**: wave-2 gate accuracy
  52% (Brier 0.38); on multi-hop scenarios 31–37% with mean P(sufficient)
  0.33–0.37 on fully answerable questions — the gate systematically
  underestimates sufficiency when evidence spans documents; the retry loop
  rescues most of it. Hybrid losses are gate false negatives with gold files
  already top-ranked (mq12 P=0.05, w210 P=0.04, w26 P=0.04).
- **New corpus builder features** (`build_public_scenarios.py`): three
  memory-safe pyarrow builders (row-group-cached reads for the 234MB TriviaQA
  parquet), merge semantics that keep existing scenarios byte-identical when
  their raw data is absent, near-empty stub filtering (2wiki), hop-class
  stratification (musique id prefixes), full provenance in the manifest;
  `pyarrow>=15` pinned in requirements.
- **Harness hardening**: `bench_resume.py` resume now defaults to the run's
  stored scenario list (a stale CLI default once contaminated a run with
  off-plan questions — caught and purged mid-run); new
  `scripts/analyze_per_scenario.py` for per-scenario summaries;
  `diagnose_public_bench.py` takes the run id as an argument.

## 2026-09-28 — Popular public RAG benchmarks: SQuAD + HotpotQA (split result)

Run `4dc6c46e`: 50 seeded questions (25 SQuAD v1.1 dev — one per article;
25 HotpotQA dev-distractor — 18 bridge / 7 comparison, all level=hard) through
the same audited two-arm protocol, judge kimi-k2.5 (self-test 8/8) on the
user-provided DashScope endpoint (qwen3.7-plus generator, qwen3.6-plus
best-of-2 candidate, kimi-k2.5 judge — all three verified live):

- **HotpotQA (multi-hop): hybrid 84% vs traditional 66% (+18pp)**, recall@4
  +16pp (72→88%), pairwise 10W/3L/12T (64%). All five large wins are
  traditional over-abstentions the corrective-retry loop recovered.
- **SQuAD (single-hop): hybrid 70% vs traditional 82% (−12pp)** — retrieval
  saturated for both arms (92% hit@4); the sufficiency gate's absolute
  threshold abstained on answerable jargon-dense passages (sq5: P=0.02,
  sq12: P=0.19 with the gold article top-ranked in both arms).
- **Pooled: +3pp (77% vs 74%), n.s.** (McNemar p=1.0, Wilcoxon p=0.426,
  bootstrap CI [−8, +14]pp); pairwise 13W/8L/29T (55%). Hybrid p50 64s vs 19s;
  hybrid cost slightly LOWER ($0.074 vs $0.089 — more concise answers).
- **Gate calibration on public data: 72% accuracy, Brier 0.22** (internal
  suite: 82–92%, Brier 0.08–0.16) — the third independent confirmation that
  the 0.8B decision model works as a relative signal (rerank/retry) and
  miscalibrates as an absolute gate.
- **Harness**: `backend/scripts/build_public_scenarios.py` (seed-42,
  provenance-in-manifest corpus builder), manifest-driven `PUBLIC_SCENARIOS`
  loader in the scenario registry, updated integrity/coverage tests.
- **Infrastructure (sandbox reset recovery)**: rebuilt venv via Tencent PyPI
  mirror (pypi.org egress flaky), re-downloaded + re-patched the Jev runtime
  (fixed a CWD bug in `setup_local_models.sh` that silently skipped the
  memory patches on fresh setups), and added
  `backend/scripts/bench_resume.py` — a resumable per-question-checkpointed
  driver around the audited runner that survives the sandbox's tool-call
  process reaper (the 94-minute run was executed as 10 chained 8.5-minute
  windows with zero lost questions).

## 2026-09-28 — Battery-off full ablation: v2 recovers v1-level numbers; gateway-auth tooling

The full 6-scenario battery-off ablation (run `bf05f585`, 48Q × 2 arms, judge
kimi-k2.5 self-test 8/8, same endpoint/models as all prior runs) **answers the
attribution question at scale**:

- **Within-run: hybrid v2 (battery off) 92.7% vs traditional 87.5% (+5.2pp,
  n.s. — McNemar p=0.375, Wilcoxon p=0.222, bootstrap CI [−3.1, +14.6])**.
  Pairwise 9W/3L/36T (56.3% win rate, position consistency 91.7%).
- **v1-level recovery: 4/6 scenarios exactly or better** (finance 100%, policy
  100% — exceeds v1's 87.5%, distractor 87.5%, outofscope 87.5%); techdocs
  87.5% and multilingual 93.75% recover most of the gap. Faithfulness 100%;
  over-abstention 39.5% → **4.7%** (v1: 2.3%); fabrications 0.
- **Fast-path remediation validated**: the o6 fabrication from run `0314ac0a`
  is gone with `jev_no_retrieval_threshold=0.9`; all 8 outofscope questions
  now score 1.0 (proper abstention on unanswerable, corpus-grounded answers on
  answerable).
- **Remaining loss taxonomy (3 pairwise losses)**: 2 rerank demotions (gold
  below top-4; hit@4 95.4% vs 100% — the battery had been masking this), 1
  judge-noise abstention flip (o5, both arms abstained identically).
- **Infrastructure**: after a sandbox reset wiped the DashScope key, added
  OpenAI-compatible gateway auth support (`JEVRAG_DASHSCOPE_AUTH_CONFIG` +
  `X-Token`/`X-Z-AI-From` headers, `build_llm_client()` shared by generator and
  judge) and a shared request pacer (`JEVRAG_LLM_MIN_REQUEST_INTERVAL`) that
  stops 429 retry death-spirals on burst-limited shared gateways. Full
  environment rebuilt from git (venv, GGUF, jev-score); DashScope key later
  restored by the user, keeping all three full runs on one endpoint/model/judge
  stack.
- Docs rewritten: `docs/benchmark-v2-ablation.md` (full-scale attribution study,
  superseding the finance-only preliminary), `docs/benchmark-results.md`
  (three-run structure: battery-off primary, battery-ON archived negative
  result, v1 archived).

## 2026-09-28 — v2 full benchmark: objective evaluation, memory hardening, evidence-based defaults

The full v2 re-run (48 questions × 2 arms, run `0314ac0a`) **changed the conclusion**,
and the repo now says so plainly:

- **Result (within-run, controlled comparison): hybrid v2 62.5% vs traditional 83.3%
  correctness (−20.8pp; Wilcoxon p = 0.033; bootstrap CI −0.40…−0.02; pairwise
  4W/24L/20T = 29.2% win rate).** The v1 result (93.8%, +8.3pp) is re-labeled
  honestly: McNemar p = 0.125 — a positive trend, underpowered at n=48, not an
  established win. Both directions get the same statistical yardstick
  (`scripts/analyze_bench_run.py`: McNemar exact/χ², Wilcoxon + rank-biserial,
  paired bootstrap CI, Wilson intervals, verbosity-bias probe).
- **Mechanistic attribution** (`scripts/diagnose_v2_losses.py`): 8/16 losses from the
  screening battery's injection noul firing 0.91–0.98 on ordinary prose (gold passages
  dropped), 3 from all-evidence drops emptying the context, 3 from conflict-flag
  hedging, 1 from a no_retrieval misroute (plus 2 judge-noise flips at the abstention
  boundary). Over-abstention 39.5% (v1: 2.3%); 1 fabrication via the no_retrieval
  fast path; sufficiency gate degraded to 82.2%/Brier 0.164 evaluating
  battery-depleted contexts.
- **Ablation confirmation** (`docs/benchmark-v2-ablation.md`, run `e98907aa`): finance
  scenario re-run with `JEVRAG_HYBRID_PASSAGE_BATTERY=false` isolates how much of the
  regression the battery alone accounts for.
- **Evidence-based default changes**: `hybrid_passage_battery` now ships **false**
  (absolute-threshold gating needs per-corpus calibration before shipping on);
  `jev_no_retrieval_threshold` 0.5 → 0.9 (misroute + fabrication evidence; validated
  chat questions still clear 0.94). `.env.example` and config comments cite the run.
- **Objectivity protocol documented** (docs/benchmark-results.md): judge independence
  + position swap + blind absolute scoring (audited, unchanged, sound); new
  confound disclosures — cloud latency/behavior drift across runs (traditional's own
  score moved with identical code), judge variance on abstention scoring, and the
  within-run vs cross-run distinction.
- **Sandbox survivability fix**: jev-score allocation trimmed ~306 MB
  (env-tunable `--n-seq-max`/`--n-outputs-max`; our exact-mode requests only use
  sequences 0/1). Verified bit-identical decisions; full 98-minute run completed
  with zero OOM incidents. RLIMIT_DATA child cap tested and rejected (context init
  fails at 1600 MB against ~1.23 GB actual RSS — llama.cpp reservations count).
  Statistics deps (scipy, statsmodels) added to the backend venv for analysis.

## 2026-09-28 — Hybrid v2 pipeline: decisions beyond model routing (single generator)

Implements the v2 proposal from the research pass — every slot was validated locally before
shipping (`docs/jev-improvements-research.md` §3-4, now marked implemented):

- **[1] Effort routing** replaces v1 model routing: one `choice`
  `{no_retrieval, single_pass, multi_step}` per query; `no_retrieval` + P ≥ 0.5 skips
  retrieval entirely (Adaptive-RAG class A fast path). `llm_model_reasoning` is now unused by
  the hybrid pipeline — one generator (qwen3.7-plus) by design.
- **[2] Multi-step retrieval**: LLM decomposition into sub-queries → per-sub-query retrieval →
  deduped pool (≤12) → rerank.
- **[3] Screening battery** (TypeSafe classifying-RAG cookbook): 3 nouls per kept passage
  (answer evidence · premise contradiction · prompt injection) → ordered thresholds
  include / conflict-block / drop; conflict-blocked passages keep their `[n]` labels and move
  to a dedicated "Conflicting evidence" prompt section.
- **[4] Corrective loop** (CRAG): insufficient context → LLM rewrites the query → re-retrieve →
  re-screen, capped at one retry.
- **[5] Best-of-2 generation** on the hard path (multi_step or low sufficiency): two concurrent
  candidates (thinking off / thinking on), Jev selects by calibrated P(grounded) — a relative
  selector, never an absolute gate.
- **[6] Citation-level verification**: ONE batched decide() — choice per emitted `[n]`
  (supports/contradicts/says_nothing, auto-accept ≥ 0.8 confidence) + whole-answer
  groundedness (v1 continuity) + answers-request nouls.
- **[7] Composite quality score** in code: `0.4·answers_request + 0.4·citations_supported +
  0.2·¬contradicts_context` (TypeSafe's own answer-gating example).
- **Bench runner mirrors v2 exactly** (DOX contract): shares prompts, engine methods, policy
  functions and System Two helpers with the production pipeline; run config records
  `pipeline: hybrid-v2`; `POST /bench/runs` accepts `max_questions` for smoke runs.
- **Frontend**: `routing` event now carries effort; message badges for effort / quality /
  best-of-2 / corrective retry; trace panel renders all 11 decision record kinds with
  per-name icons and scalar/array answers; **recreated the accidentally-lost
  `src/lib/jevrag/types.ts`** (the frontend did not build without it).
- **Hermetic tests**: `tests/test_v2_pipeline.py` covers parse_citations, battery policy
  ordering (injection > conflict > evidence, relevance rescue), citation summary/confidence
  auto-accept, composite formula, and every new engine method with a mocked decide() (35 pass).
- **Live verification**: single_pass (116 s, caught a real premise conflict and answered
  through it), multi_step (178 s: decompose → insufficient → corrective retry → best-of-2 →
  contradicted citation caught), no_retrieval (23 s, P=0.946); browser-verified traces with
  zero console errors; bench smoke (techdocs × 1): both arms correct, hybrid hit1/MRR/NDCG
  all 1.0, judge self-test 8/8.
- Known trade-off (documented in `docs/hybrid-design.md`): v2 latency on 2 CPU cores —
  ~116 s single_pass / ~178 s hard path vs ~30 s v1 — every slot is individually switchable.

## 2026-09-28 — Research: Jev beyond routing / single-model design

- **Research pass** (two websearch agents + local experiments):
  [docs/jev-improvements-research.md](docs/jev-improvements-research.md) answers "what if
  there were only one cloud model?" — routing degenerates into whether/how/how-many-times
  to invoke the single model, plus which candidate output to keep — with published evidence
  (Adaptive-RAG, CRAG, FrugalGPT/RouteLLM/Hybrid-LLM, verifiers/Speculative-RAG, TypeSafe's
  own patterns/cookbooks) and 11 ranked improvement patterns for Jev-style decision models
  in RAG pipelines.
- **Local validation experiments**
  (`backend/scripts/experiment_single_model_routing.py`): effort routing 3-way choice
  **9/12** (and the `no_retrieval` probability cleanly separates chat from doc questions —
  a safe skip-retrieval fast-path); best-of-2 selection picks the faithful answer
  (**0.973 vs 0.817**, one call); per-citation `supports/contradicts/says_nothing` check
  **3/3**. Includes a v2 pipeline proposal and a "what NOT to build" list from published
  negative results.

## 2026-09-28 — Presentable & documented

- **Repo beautification**: README with screenshots, results-at-a-glance tables, mermaid
  architecture diagram, guided quickstart and repository tour; Apache-2.0 `LICENSE`;
  this `CHANGELOG.md`; GitHub repo description + topics.
- **Bug fix** (found while screenshotting): the per-scenario **Hit@4 / MRR@10 charts** in the
  Benchmarks dashboard rendered empty because they read retrieval metrics from the wrong
  level of the summary object (`arm[field]` instead of `arm.retrieval[field]`).
  Correctness and faithfulness charts were unaffected.

## 2026-09-27 — Benchmarking & comparison (Phase 3)

- [`3a950d2`](https://github.com/kanishka-namdeo/jev-rag/commit/3a950d2) — **Benchmarks Lab UI**
  (scenario cards, live progress polling, results dashboard with metric cards + delta chips,
  four per-scenario comparison charts, pairwise / gate / rerank-lift panels, abstention table,
  per-question drill-down with full judge reasoning) · methodology doc · exported full-run
  results.
- **Full benchmark run completed**: 48 questions × 2 systems, 96 result rows, 0 errors, 31.9 min
  (run `9d894b6c`).
  Headline: hybrid correctness **93.8% vs 85.4%** (+8.4pp), earnings-distractor scenario
  **75% → 100%**, over-abstention **14% → 2.3%**, zero fabrications, Jev gate accuracy **91.7%**
  (Brier 0.077), pairwise win rate 54.2% (6W/40T/2L), judge self-test 8/8.
  Honest tradeoff documented: hybrid latency p50 30.5 s vs 1.5 s (three local decision calls).
- [`77993b2`](https://github.com/kanishka-namdeo/jev-rag/commit/77993b2) — run hygiene: memory
  trim per question, orphaned-run reaping at startup.
- [`be74274`](https://github.com/kanishka-namdeo/jev-rag/commit/be74274) ·
  [`48b94f5`](https://github.com/kanishka-namdeo/jev-rag/commit/48b94f5) — **OOM resilience**:
  `JEV_SCORE_N_CTX=8192` cap, engine reload + retry on subprocess death, `MALLOC_ARENA_MAX=2`.
  Root lesson recorded in DOX: no eslint/browser/node tooling during long local-model runs.
- [`472c2a0`](https://github.com/kanishka-namdeo/jev-rag/commit/472c2a0) — **benchmarking
  harness**: six scenario corpora (26 documents, 48 ground-truth QA pairs — techdocs, finance
  distractors, conditional policies, needle KB, multilingual EN/ZH/DE/FR, out-of-scope
  abstention) · deterministic retrieval metrics (hit@k, MRR, recall@k, file-level nDCG@10 —
  including a duplicate-gold-chunk fix) · independent LLM judge (`kimi-k2.5`, JSON-only,
  temperature 0, 8-canary self-test) for correctness/faithfulness + 3-way abstention ·
  MT-Bench pairwise with position swap + consistency audit · `bench_runs`/`bench_results`
  persistence · API under `/api` and `/backend-api` · 22 passing tests.
  Design was grounded in a dedicated research pass over RAGAS / DeepEval / ARES / G-Eval /
  MT-Bench / GRAB-RAG / AbstentionBench methodology.

## 2026-09-27 — System & docs (Phase 2)

- [`ab7daae`](https://github.com/kanishka-namdeo/jev-rag/commit/ab7daae) — **DOX framework**
  (root `AGENTS.md` with project-wide contracts + child docs for `backend/`, `src/`, `scripts/`,
  `docs/`) · docs (architecture, hybrid design, API) · CI workflow (hermetic pytest + lint) ·
  Caddy proxy + Next rewrite so the API works in all hosting contexts · self-healing backend
  (`/api/ensure-backend` spawns uvicorn detached) + SSE retry after re-ensure.
- Live-browser verification of every surface: traditional chat, hybrid chat (context 0.84,
  grounded 93%), compare mode side-by-side, upload via UI, trace panel with all four Jev
  decisions, mobile layout, zero console errors.

## 2026-09-27 — Initial system (Phase 1)

- [`a976e87`](https://github.com/kanishka-namdeo/jev-rag/commit/a976e87) — **first working
  hybrid RAG system**:
  - Backend (FastAPI): Dashscope client with thinking-suppression + cost estimation; local
    Jev engine (Jev-Style-0.8B GGUF on a custom llama.cpp `jev-score` build); ingestion via
    markitdown + langchain-text-splitters + fastembed (multilingual MiniLM) + ChromaDB;
    traditional and hybrid pipelines with an SSE event protocol; conversations/messages/trace
    persistence in SQLite; 5 hermetic tests.
  - Frontend (Next.js 16 + Tailwind 4 + shadcn/ui): chat with compare rows, markdown +
    citation chips, trace panel with probability bars, document upload, conversations,
    status pill, dark mode.
  - **Measured decision patterns** (the core research result): generic shared-state statements
    give zero discrimination (0.97 vs 0.02 in a bad pattern), while passage-text-in-question
    single-call scoring wins — adopted for `rerank_chunks`.
  - Local System One selection was grounded in verified HF metadata: Jev itself is
    closed-weights/cloud-only, so the open stand-in is Jev-Style-0.8B-Decision-v3 (Q4_K_M,
    529,296,864 bytes, Apache-2.0); endpoint model split chosen from published strengths
    (qwen3.7-plus = faster/cheaper/agentically stronger default; qwen3.6-plus = always-on CoT
    for the deep-reasoning route).

## 2026-09-29 — v3 upgrade: 2026-standard retrieval + gate inversion + hypothesis testbench

Both pipelines were upgraded to current production RAG practice, the Jev model
was re-placed on evidence, and the whole thing was measured with a pre-declared
hypothesis testbench. Research → design → implementation → measurement, one
commit per milestone:

- **Research (3 parallel agents)**: 2025-26 RAG practice survey, small-model
  placement literature, full code audit → [docs/rag-upgrade-2026.md](docs/rag-upgrade-2026.md) (design of record).
- **New retrieval stack (both arms)**: BM25 ‖ dense + reciprocal-rank fusion,
  ONNX cross-encoder rerank (replaces the Jev pointwise rerank on the hot path),
  structure-aware chunking with contextual title/section prefixes — zero new
  dependencies, CPU-only, all local.
- **Gate inversion (the core fix)**: v2 asked the 0.5B model for absolute
  sufficiency judgments BEFORE retrieval (single-hop −7.3pp, 3× latency, gate
  acc 72%/Brier 0.38). v3 always retrieves first and escalates to the hard path
  on a calibrated score-feature gate (top-1 rerank score; acc 0.898, Brier 0.103).
  Heavy stages (decompose, screening battery, CRAG retry, best-of-2) now run
  ONLY on the hard path; effort routing runs concurrently with retrieval.
- **Jev re-placement**: kept for relative judgments (best-of-2 selection,
  citation verification, chat-vs-doc routing); removed from absolute sufficiency
  and hot-path rerank — every removal backed by measurement, not taste.
- **Structural arm parity**: the bench runner's 230-line hand-maintained mirror
  of the hybrid pipeline is deleted; both arms drive the SAME ChatService
  orchestrator (arm divergence is now impossible by construction).
- **Hypothesis testbench**: two pre-declared layers — offline retrieval eval
  (7 arms, gate calibration) and a resumable pipeline ablation runner
  (gate/rerank/selection/verification arms with never/always/oracle bounders),
  exact McNemar + paired bootstrap + BH-FDR:
  [docs/testbench-design.md](docs/testbench-design.md),
  [results Layer-1](docs/testbench-results-layer1.md).
- **Measured (run 16814bd5, 98 public questions, 0 errors)**: pooled +5.1pp
  (p=0.065); **single-hop −7.3pp → +9.8pp, significant (Wilcoxon p=0.048)**;
  multi-hop compressed to +1.8pp n.s. because the upgraded baseline got good;
  over-abstention 35.7% → 25.5%; latency 3× → 2.06×; hybrid still cheaper.
  H-GATE ablation (run 6b58fc40): features gate 0.70 > never 0.65 > always 0.60
  at 2.6× lower latency than always-escalating — direction confirms the design.
  All numbers with n/CI/statistics:
  [docs/rag-upgrade-2026-results.md](docs/rag-upgrade-2026-results.md).
- **Known negatives, kept visible**: the cross-encoder rerank *hurts* on
  MuSiQue (recall 0.635 → 0.557, compositional gold doesn't look "relevant");
  wiki2 stays hard for both arms (0.28); the bge embedding swap was REJECTED
  (−1.9pp, n.s.); the gate's top-1 score remains a weak signal for
  gold-in-top-4 (θ* = 0.987 acc 0.59) — full honesty tables in the results docs.
