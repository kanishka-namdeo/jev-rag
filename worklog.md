# Jev-RAG Worklog

Single shared work log for all agents working on this repo. Append-only; each
section starts with `---`. Newest at top.

---
Task ID: 12
Agent: main (Super Z)
Task: write clear setup instructions/guides linked to fresh-system setup
instructions; proactively ensure code compatibility for setting the project up
on another system; push changes to repo

Work Log:
- Third sandbox reset recovery rode on top of the portability work itself: the
  fixed scripts WERE the fresh-machine validation (venv rebuilt via fixed
  setup_backend.sh with UV_INDEX_URL mirror; models+jev-score rebuilt via fixed
  setup_local_models.sh incl. new pip-bootstrap path with JEVRAG_PIP_INDEX_URL
  mirror override; backend booted healthy in 15s launched from /tmp via fixed
  backend_service.sh)
- Portability audit found + fixed: hardcoded /home/z/my-project in
  setup_backend.sh / setup_local_models.sh / backend_service.sh /
  ensure-backend route.ts / init-fullstack-reference.sh / 8 diagnostics
  scripts / 4 backend experiment scripts; GNU-only stat -c%s (macOS break);
  hardcoded Tencent mirror for cmake bootstrap; probe_public_gateway.sh had
  the API key hardcoded (now reads backend/.env/env — flagged key rotation to
  user since old key lives in git history); corrupted CI trigger
  (branches: ain] -> [main]); analyze_bench_run.py --db arg was parsed but
  ignored (stale default ./db/custom.db)
- backend/app/config.py: REPO_ROOT + _anchor_path() — relative .env paths and
  .env discovery now resolve against repo root (CWD-independent; verified
  identical from repo root, backend/ and /tmp); .env.example paths updated to
  repo-root-relative
- NEW docs/setup.md: requirements (hw/os/sw/network), 5-step setup,
  path-anchoring contract, verification, benchmark reproduction (public suite
  ships in-repo, zero downloads), day-2 ops, troubleshooting table,
  portability guarantees
- Cross-links: README quickstart + docs table + milestones table (also fixed
  stale "this commit - v2" row -> real hashes + added missing public-bench
  milestone rows); DOX pass on root/scripts/docs/backend AGENTS.md; CHANGELOG
  entry; worklog (this entry)
- Git hygiene: untracked .next/** (~250 build-artifact files), dev.log, stale
  root .env; .gitignore += .env
- Verification: 35/35 pytest, bun lint clean, endpoint probe OK via
  backend/.env (all 3 models), backend health 200 from neutral cwd

Stage Summary:
- Repo is now portable: fresh-clone -> docs/setup.md -> running stack, with
  the exact path re-validated on a wiped sandbox (documented in the guide +
  CHANGELOG)
- Key rotation recommended: the user-provided Dashscope gateway key was found
  hardcoded in scripts/probe_public_gateway.sh and lives in pushed git
  history (removed from HEAD now, but rotate if repo is shared)
- Environment fully restored for future bench work: venv + models + backend
  all live again post-reset

---
Task ID: 11
Agent: main (Super Z)
Task: add more popular RAG benchmarks (user: "add more benchmarks and continue
testing"); same DashScope endpoint + PAT push

Work Log:
- Second full sandbox reset recovery: rebuilt venv (uv + Tencent mirror),
  models (GGUF + llama.cpp + jev-score, flags verified live: seq2/out32 trim),
  backend/.env (absolute paths), probed all 3 gateway models OK (json mode OK);
  bench smoke 2 questions passed end-to-end (run 9fa5079a, throwaway)
- Downloaded 3 new public benchmark parquets from HF: TriviaQA rc.wikipedia
  validation (234MB, 7993 rows), 2WikiMultiHopQA validation (29.5MB, 12576),
  MuSiQue-Ans validation (11MB, 2417) -> backend/data/public_bench/raw/
- Extended build_public_scenarios.py with three builders (pyarrow, memory-safe
  row-group cache for TriviaQA): triviaqa (16 Q answer-verified, 64-doc corpus
  padded with other questions' wiki pages), wiki2 (16 Q stratified by ACTUAL
  split types: 7 compositional/4 comparison/3 bridge_comparison/2 inference —
  the expected 'bridge' label doesn't exist in this parquet; 132 docs after
  dropping <80-char non-gold stubs), musique (16 Q stratified by hop class
  from id prefix: 8/5/3; 282 docs). Merge semantics: existing squad/hotpotqa
  kept verbatim in manifest (their raw data was wiped by the reset); new
  scenarios append only. All provenance baked into the manifest
- pyarrow>=15 added to requirements.txt (parquet reads); 35/35 tests pass
- git core.fileMode=false (sandbox reset flips exec bits -> pure noise)
- NOTE: `chmod -R 644` on corpus dirs strips dir x-bits -> use 644 files +
  755 dirs (recovered immediately, tests re-verified)

Stage Summary:
- Public suite now 5 benchmarks / 98 questions: SQuAD 25, HotpotQA 25,
  TriviaQA 16, 2WikiMultiHopQA 16, MuSiQue 16 — single-hop x3, multi-hop x3
  (distractor-style, structured-evidence, compositional-adversarial)
- RUN bcfdd120 COMPLETE (48/48, 0 errors, ~125 min, 14 chained windows):
  MuSiQue +25pp (12.5->37.5, recall@4 +13pp, trad collapses with 13/16
  abstentions), 2Wiki +12.4pp (43.8->56.2, recall@4 +9.4pp), TriviaQA 0pp
  (75/75 tie — retrieval saturated 94% both arms, hybrid 3x latency for
  nothing). Pooled +12.5pp n.s.; 5-benchmark pooled +7.6pp; multi-hop subset
  +18.4pp, single-hop subset -7.3pp. Judge kimi-k2.5 self-test 8/8, pairwise
  14W/3L/31T (61.5%), pos-consistency 83%.
- Gate story (4th confirmation): wave-2 accuracy 52%/Brier 0.38; multi-hop
  scenarios 31-37% acc with mean P 0.33-0.37 on ANSWERABLE questions; hybrid
  losses = gate false negatives with gold top-ranked (mq12/w210/w26 P=0.03-0.05)
- Ops: bench_resume resume-default bug fixed (stale CLI default contaminated
  run with 4 squad questions — purged 8 rows mid-run); docs wave2 +
  benchmark-results verdict + README table + CHANGELOG updated

---
Task ID: 10
Agent: main (Super Z)
Task: run popular public RAG benchmarks on this setup and compare; update docs
(user-provided DashScope endpoint: coding-intl.dashscope.aliyuncs.com/v1 with
qwen3.7-plus / qwen3.6-plus / kimi-k2.5)

Work Log:
- Probed sandbox after reset: tools alive; git history intact (milestone
  78ab6ea battery-off ablation already committed); worklog/venv/models/data/.env wiped
- Restored backend/.env with user's endpoint + v2 shipped defaults (battery OFF,
  no_retrieval >= 0.9); absolute paths (backend cwd resolution bug: .env.example
  had repo-relative paths that resolve wrong from backend/)
- Rebuilt environment: venv via Tencent PyPI mirror (pypi.org egress 503/timeout
  from sandbox; aliyun mirror stale, tuna 403s wheels — tencent serves both);
  GGUF + llama.cpp + jev-score rebuilt (HF CDN 4.3MB/s)
- FIXED setup_local_models.sh CWD bug: patch heredocs used root-relative
  Path() while script cwd=$MODELS_DIR -> patches silently never applied on
  fresh setups; now JEV_PATCH_TARGET absolute env var (applied + verified:
  JEV_SCORE_N_CTX + N_SEQ_MAX/N_OUTPUTS_MAX live in runtime)
- Verified all three models live on the endpoint (probe_public_gateway.sh:
  qwen3.7-plus, qwen3.6-plus, kimi-k2.5 + json_object response format OK)
- Built public benchmark scenarios (backend/scripts/build_public_scenarios.py):
  SQuAD v1.1 dev (25 Q, 1/article, seed 42, full-article corpus, 817KB) +
  HotpotQA dev-distractor (25 Q: 18 bridge/7 comparison — dev is 100% level=hard;
  corpus = union of 10-para contexts dedup by title, 250 docs 146KB; gold = 2
  supporting titles verified in-context; dedup'd gold lists after finding dupes)
- scenarios.py: INTERNAL_SCENARIOS + manifest-driven PUBLIC_SCENARIOS loader
  (provenance baked in); tests updated (35 pass); .gitignore hardened
  (backend/.env, backend/data/, models/, vendor/, logs/, .next/)
- Commit 42e2c7f (was c69d8cd before the 2026-09-29 history scrub) pushed:
  public benchmark integration milestone
- DISCOVERED sandbox reaper: controller (/app main.py, root) kills ANY
  tool-call-spawned user process seconds after the call ends (verified with
  disowned/setsid/pty test processes — all dead <100s); only the root-booted
  service tree survives. next-server (killed for RAM earlier) was the only
  surviving user process; ensure-backend route (children of next-server
  persist) unreachable without it. No watchdog revival; controller API on
  :12600 exposes only /ping
- SOLUTION: backend/scripts/bench_resume.py — resumable driver around the
  AUDITED BenchRunner internals (same _run_question code path: both arms,
  independent judge, pairwise; same config snapshot; per-question atomic
  commit; ingestion reuse when docs present). 2-question smoke passed
- Executed run 4dc6c46e as 10 chained ~8.5-min tool-call windows: 50/50
  questions, 0 errors, 94.5 min total, RAM stable (~600MB used + jev-score)
- Analysis (scripts/analyze_bench_run.py + scripts/diagnose_public_bench.py):
  overall hybrid 77% vs trad 74% (+3pp, McNemar p=1.0, Wilcoxon p=0.426,
  CI [-8,+14]pp; pairwise 13W/8L/29T 55%, pos-consistency 86%)
- Exported results (backend/scripts/export_bench_results.py) -> restored
  benchmark-results.md (export overwrote it — restored from git, new section
  added), docs/benchmark-public.md (full detail + stats + taxonomy), README
  refreshed (stale v1-primary blockquote -> current 3-evidence summary +
  public table), CHANGELOG entry added

Stage Summary:
- RUN 4dc6c46e COMPLETE: HotpotQA +18pp (66->84, recall@4 +16pp, 64% pairwise,
  all large wins = trad over-abstentions recovered by retry); SQuAD -12pp
  (82->70; gate false-negatives sq5 P=0.02/sq12 P=0.19 with gold top-ranked
  both arms; +2 judge-boundary generation losses); pooled +3pp n.s.; hybrid
  p50 64s vs 19s, cost LOWER ($0.074 vs $0.089, more concise answers);
  gate on public data 72% acc/Brier 0.22 vs 82-92% internal — third
  independent confirmation of the relative-vs-absolute threshold lesson
- Docs updated: benchmark-results.md (4 runs + verdict extension),
  benchmark-public.md (new), README, CHANGELOG; committing with this push
- Ops knowledge: reaper-proof pattern = bench_resume.py chained windows;
  PyPI via Tencent mirror; HF/GitHub fine

---
Task ID: 1-9 (pre-reset history, reconstructed from git + docs)
Agent: prior sessions
Task: hybrid RAG system, v1/v2 pipelines, benchmark harness, bias audit,
OOM resilience, v1 run 9d894b6c (+8.4pp), v2 battery-on run 0314ac0a
(-20.8pp, Wilcoxon p=0.033), battery-off recovery run bf05f585 (+5.2pp n.s.)
Stage Summary:
- All documented in docs/benchmark-results.md, docs/benchmark-v2-ablation.md,
  CHANGELOG.md, git log (ab7daae..78ab6ea)

---
Task ID: 10 — history scrub (secrets removal)
Agent: Super Z (main agent)
Task: "scrub history to remove the key or something similar" — remove the
leaked DashScope API key (and any similar secrets) from git history, then
push the cleaned history to the repo.
Work Log:
- Full-history sweep of all 23 commits: the real key lived ONLY in
  scripts/probe_public_gateway.sh (introduced c69d8cd, scrubbed from HEAD
  in fb63b82 but still present in pushed blobs); GitHub PAT never entered
  history; remaining sk-* hits were Tailwind/CSS artifacts inside .next
  build cache (false positives)
- Also found ~255-265 .next/dev cache files (binary turbopack SST blobs,
  machine-specific paths) committed across 6 commits — purged in same pass
- git-filter-repo --replace-text (key -> REDACTED-DASHSCOPE-KEY) +
  --path .next --invert-paths: 8 commits rehashed, 78ab6ea and older stable
- Verified: git log -S / git grep across all revs -> zero hits; .next gone
  from every commit; HEAD tree byte-identical (943 files); worktree clean
- Repointed stale commit refs in README.md changelog + this worklog
- Force-pushed rewritten main to origin
Stage Summary:
- History is secret-clean and pushed; MBs of .next SST junk removed
- Hash map (old -> new): ba18ab2>a4b2542, c69d8cd>42e2c7f, 48b8b31>bb7a8b4,
  3856726>9d829a6, fcbf003>89f9d1b, c2a1034>f1acea8, fb63b82>aab887a,
  881882e>24c8116 (78ab6ea and earlier unchanged)
- ACTION STILL REQUIRED (user): rotate the DashScope key (it lived in
  pushed history and in chat); consider rotating the GitHub PAT too. Old
  commit objects may remain reachable on GitHub via direct SHA until GC

---
Task ID: 11 — repo beautification (user-friendly README + community files)
Agent: Super Z (main agent)
Task: "readme is too text heavy, we want a user friendly experience for people
visiting this repo. check online how to do this and beautify the repo overall
while following best practices and implement them. push changes to repo"
Work Log:
- Researched online: README best-practice searches + Standard Readme spec
  (section order, badges, TOC, security/contributing sections, no broken links)
  and repo-beautification patterns (visual-first hierarchy, collapsibles)
- README rewritten 302→336 lines but ~60% less visible text: centered banner →
  pitch → badges (+PRs Welcome) → stat strip → hero screenshot → emoji section
  nav; screenshots moved to top; interpretation prose, full config table,
  milestones, DOX/agent notes moved into 5 <details> collapsibles; all numbers,
  caveats and negative results preserved (objectivity contract intact)
- New community files: CONTRIBUTING.md, SECURITY.md
- New .github: ISSUE_TEMPLATE/bug_report.md + feature_request.md + config.yml
  (contact links), PULL_REQUEST_TEMPLATE.md (safety + evidence checklist)
- scripts/validate_readme.py: link/anchor/image/details/secret audit — CLEAN
  (fixed one fragile emoji-variation-selector anchor 🗂️→📁)
- Social preview card: scripts/social_preview.html + render_social_preview.py
  (Playwright, 1280x640 @2x → docs/assets/img/social-preview.png, VLM-verified);
  GitHub REST upload endpoint 404s for PATs — image ships in repo for manual
  upload via Settings → Social preview
- DOX pass: scripts/AGENTS.md ownership updated with the 3 new scripts;
  CHANGELOG.md entry added; root AGENTS.md unchanged (no contract change)
Stage Summary:
- Repo surface now follows published best practices: scannable visual README,
  contribution/security policies, structured issue+PR flows
- README validation green; all 16 commit links and doc anchors verified
- Social preview: image in repo, needs one manual upload by maintainer

---
Task ID: 1
Agent: Super Z (main agent)
Task: Clone and set up https://github.com/kanishka-namdeo/jev-rag.git in the space-z.ai sandbox; configure Dashscope endpoint (coding-intl.dashscope.aliyuncs.com/v1) with qwen3.7-plus / qwen3.6-plus / kimi-k2.5; store GitHub PAT.

Work Log:
- Cloned repo to /home/z/my-project/jev-rag; validated PAT (owner kanishka-namdeo, push access) and stored it in /home/z/my-project/.git-credentials with repo-local credential.helper (store --file) + user identity; added .git-credentials/download/upload to .gitignore (only tracked change, uncommitted).
- Created backend/.env from .env.example: JEVRAG_DASHSCOPE_API_KEY set, base URL and all three models already match the repo defaults (qwen3.7-plus default, qwen3.6-plus reasoning, kimi-k2.5 judge).
- Probe script verified the endpoint: /models lists all three; chat smoke OK for all three; kimi-k2.5 judge JSON mode OK.
- GGUF download (529,296,864 bytes) kept stalling via the repo script's plain curl; wrote .zscripts/dl_gguf.sh (resumable, --speed-limit stall detection) and completed the download; re-ran scripts/setup_local_models.sh for runtime patches + llama.cpp shallow clone + jev-score build (STATUS: SUCCESS).
- scripts/setup_backend.sh: backend/.venv created via uv; sanity imports OK (fastapi 0.141.1, chromadb 1.5.9, fastembed 0.8.1, jev_style 0.3.0). bun install: 827 packages.
- Discovered the sandbox reaps tool-call-spawned processes between calls; ran the platform fullstack init (curl z-cdn.chatglm.cn/fullstack/init-fullstack.sh | bash) which sets up .zscripts/dev.sh (supervised, persistent Next.js dev server on :3000).
- Moved the whole jev-rag repo (incl. .git, backend, models, vendor, scripts) from /home/z/my-project/jev-rag to /home/z/my-project so the platform dev server serves it; removed the scaffold app (src/public/prisma/db/examples/mini-services); removed leftover build caches.
- Relocating broke jev-score: build_jev_score.sh bakes an absolute DT_RUNPATH, and its DT_RUNPATH only covers direct NEEDED (libllama), leaving transitive libggml/libggml-cpu unresolved. Fixed by RELINKING build/jev-score with -Wl,--no-as-needed -lllama -lggml -lggml-base -lggml-cpu and -Wl,-rpath,'$ORIGIN/../../../vendor/llama.cpp/build/bin' (position-independent; models/ is gitignored so no tracked file changed). Patch helper kept at .zscripts/patch_jev_score_rpath.py.
- Started the stack: .zscripts/dev.sh (next dev :3000, persistent) + ensure-backend route self-heals FastAPI on :8000 (detached child of next-server — survives sandbox reaping).
- Verified in browser (agent-browser): UI renders; system status all green (dashscope ok, jev engine ok 2.73s, embeddings ok); uploaded scripts/test-assets/sample-knowledge.md (3 chunks); Traditional query answered correctly with citation [1] (19.8s, $0.0015); Hybrid · Jev query answered correctly (context 0.91, quality 98%, grounded 96%, 40.4s, $0.0013); trace panel works. Screenshots: download/jev-rag-hybrid-chat.png, download/jev-rag-trace-panel.png.
- Backend hermetic tests: 35/35 passed in 6.65s. Frontend lint: clean.

Stage Summary:
- Full stack running in the sandbox: Next.js 16 on :3000 (supervised via .zscripts/dev.sh), FastAPI on :8000 (self-healed via /api/ensure-backend), Caddy :81 gateway (repo Caddyfile matches platform XTransformPort routing).
- Dashscope endpoint + all three requested models configured and verified working (probe + live chat + judge JSON mode).
- GitHub PAT stored at /home/z/my-project/.git-credentials (git credential.helper store --file, repo-local); repo history intact at HEAD c05f7f5; only local uncommitted change: .gitignore platform additions.
- jev-score is now position-independent ($ORIGIN rpath + no-as-needed link); note for fresh installs: a plain rebuild re-bakes an absolute rpath — relink step documented here is the fix if the tree moves post-build.
- Known sandbox quirks handled: tool-call processes are reaped (use the ensure-backend route / .zscripts/dev.sh instead of manual uvicorn); HuggingFace GGUF downloads stall (use .zscripts/dl_gguf.sh).
