# End-user docs and README redesign

Date: 2026-10-01
Status: design approved in brainstorm, pre-implementation
Classification: architectural — this restructures the documentation surface and the
link/DOX contracts that hang off it.

## 1. Problem

The repo's docs are accurate but written for the person who built it. Concretely:

1. **`docs/` has no door.** 23 markdown files sit flat in one directory (22 content docs
   plus `AGENTS.md`, which is an agent contract, not an index). The only "index" is
   `docs/AGENTS.md`'s Ownership list, written in maintainer voice.
2. **No end-user task documentation exists.** `setup.md` gets a user to `localhost:3000`;
   after that there is nothing on uploading, modes, reading citations, tuning, or
   recovering. `api.md` is the wire protocol, not a guide.
3. **The README's headline is indefensible.** `README.md:18` claims `0` fabrications beside
   numbers from run `16814bd5`, whose five public scenarios contain **zero unanswerable
   questions** — so `fabrication_rate` is `None` for that run by construction
   (`backend/app/bench/runner.py:541-542`).
4. **The README contradicts the repo's newest benchmark record.** `docs/AGENTS.md` binds
   "no arm beats `base` at FDR q<0.05 … cite both draws or neither"; `README.md:157-190`
   asserts the hybrid wins and cites one draw.
5. **Numeric drift between README and docs.** Disk: `README.md:53` "~2 GB" vs
   `docs/setup.md:33` "~5 GB min / 8 GB comfortable". Setup time: `docs/setup.md:74`
   "~10 minutes" vs `docs/setup.md:3` "~15 min". GGUF size appears as `~505 MB`,
   `0.53 GB`, and `529,296,864 B`.
6. **A dead link shipped.** `docs/setup.md:97` points at `README.md#configuration-backendenv`;
   no such anchor exists, and no configuration reference exists anywhere (62 fields in
   `app/config.py`, 37 in `backend/.env.example`, ~25 in neither).
7. **The privacy claim outruns the default binding.** `scripts/dev.sh:21`,
   `scripts/backend_service.sh:19` and `backend/app/main.py:124` all bind `0.0.0.0`;
   CORS is `allow_origins=["*"]` (`main.py:104`); there is no auth anywhere. Anyone on the
   user's LAN can chat, upload, delete documents and read every conversation, while
   `README.md:45` advertises "local-first, privacy-preserving".
8. **Repo surface carries dev diaries.** `worklog.md` (948 lines) at root and
   `docs/project-status-2026-09-30.md` (516 lines) are append-only task logs, which
   `docs/AGENTS.md` Local Contracts explicitly says do not belong in durable docs.
9. **Asset defects.** `docs/assets/img/social-preview.png` is 2560×1280 / **1.07 MB**, over
   GitHub's documented **under 1 MB** social-preview cap; its generator hardcodes
   `OUT = '/home/z/my-project/...'` (`scripts/render_social_preview.py:6`), violating the
   root AGENTS.md "never hardcode absolute paths" rule. `README.md:31` and `:36` embed the
   same `chat-compare.png` twice. The README mermaid forces a dark theme
   (`background: #0B0F19`) that renders as a black slab in light mode. 3.9 MB of the 6.7 MB
   image directory is unreferenced.

## 2. Decisions taken in brainstorm

| Question | Decision |
| --- | --- |
| Primary end user | **Self-hosting users first**; evaluators get a clearly separated tier |
| Docs surface | **In-repo, GitHub-rendered.** No hosted docs site |
| Restructure depth | **Stable paths** — no existing doc moves; add hub + prune diary |
| Benchmark framing | **Honest evidence is the selling point** — headline plus "what we could not show" |
| Beautify scope | **Repo presentation only.** App UI untouched; no demo GIF |
| Tidying | **Tidy** — move (not delete) diaries, add low-value-but-expected `.github` files, prune provably dead assets |
| Privacy fix | **Docs + minimal security fix** — in scope, including the gate-default correction |
| Structure | **Approach A** — user layer, minimal surface |

Rejected with reasons: a hosted docs site (Material for MkDocs entered maintenance mode
Nov 2025, successor Zensical; framework churn plus owning DNS/search/CI is not worth it for
a 23-file tree); a new `docs/quickstart.md` (`setup.md` already is the on-ramp, and a second
install page is exactly where the disk/time drift in §1.5 came from).

**Delivery order.** This is one documentation subsystem, so it stays one spec — but §7 lands as
its own milestone commit with its own gates (code + `.env.example` + tests + bench smoke), because
it is the only part that changes runtime behavior. Everything else is files: hub and user pages →
README → assets and visual fixes → diary move and `.github` → link checker and DOX closeout.

## 3. Target information architecture

```
README.md                       rewritten, user-first order (§4)
docs/README.md                  NEW — human hub, three lanes
docs/usage.md                   NEW — day-to-day tasks (§5)
docs/configuration.md           NEW — every knob + default + restart rule (§5)
docs/troubleshooting.md         NEW — symptom-first (§5)
docs/setup.md                   path unchanged; install+verify; links the three above
docs/dev/                       NEW — worklog.md + project-status-2026-09-30.md move here
docs/dev/AGENTS.md              NEW — child DOX: raw logs and dated snapshots, not contracts
docs/AGENTS.md · AGENTS.md      DOX ownership + index updated in the same commit
```

Every other path stays byte-identical: `architecture.md`, `hybrid-design.md`, `glossary.md`,
`api.md`, `results.md`, `benchmarking.md`, `testbench-*.md`, `benchmark-*.md`,
`rag-upgrade-2026*.md`, `parallel-bench-runbook.md`, `setup-gpu.md`, `windows-setup.md`.
The hub sorts them; nothing renames them.

Hub lanes (Diátaxis-shaped without importing its vocabulary):

- **Use it** → `setup.md` → `usage.md` → `configuration.md` → `troubleshooting.md`
- **Understand it** → `glossary.md` → `architecture.md` → `hybrid-design.md` →
  `rag-upgrade-2026.md` → `api.md`
- **Measure it** → `results.md` → `benchmarking.md` → `testbench-design.md` → run reports →
  `parallel-bench-runbook.md`

## 4. README specification

Target ≤200 lines (from 231) while adding three sections and cutting the oversized diagram.

| # | Section | Content contract |
| --- | --- | --- |
| 1 | Banner + one sentence | existing `docs/assets/img/banner.svg`; one plain line on what it is |
| 2 | Badges | **4 functional only**: CI · license · backend (Python/FastAPI) · frontend (Next.js). Drop `PRs welcome` and the `architecture: local-first` vanity badge — local-first becomes a real section |
| 3 | What it does | upload → ask → cited answer. Name the **11** accepted extensions (`ingestion.py:23`), not the 7 the dropzone text advertises. Two pipelines + Compare |
| 4 | Who it's for / what it is **not** | single user; one shared knowledge base (`db.py` has no user column); no multi-tenancy; exactly one cloud call |
| 5 | Screenshots | one hero, then a 2-up of the other three. No image appears twice |
| 6 | Requirements + quickstart | table: OS, 2 cores min / 4+ comfortable, 4 GB min / 8 GB comfortable, **5 GB disk min / 8 GB comfortable**, GPU optional with the WSL2 ONNX CPU-fallback caveat; then the 4 existing commands; then "open localhost:3000" |
| 7 | Which mode should I use | Traditional / Hybrid / Compare. State plainly that Compare is two concurrent runs client-side (`store.ts:215-225`), not a third pipeline, and that the groundedness badge is hybrid-only (`pipelines.py:259-262`) |
| 8 | How it works | mermaid shrunk to ≤15 lines, **no theme override** so it follows the viewer's theme, with `accTitle`/`accDescr`; two short paragraphs on the escalation gate and the 0.8B decision model |
| 9 | Results | the honest panel below |
| 10 | Privacy | what stays on disk, what leaves (one generation call), **the default bind is loopback**, and how to opt into LAN access |
| 11 | Documentation | the three lanes, mirroring `docs/README.md` |
| 12 | Contributing · Security · Credits · License | links only; no new prose |

**No manual TOC / link-ladder.** GitHub auto-outlines READMEs and the top repos (ollama,
Dify, khoj, AnythingLLM) rely on it. Instead, after the rewrite every anchor referenced from
`docs/` or `CONTRIBUTING.md` is hand-verified, because emoji-heading anchors are a documented
breakage source and a dead anchor already shipped once (§1.6). Emoji stay in headings.

**Section 9 — the honest panel.** Table over chart, with conditions printed beside numbers:

| | v3 headline `16814bd5` | Layer-2 9-arm `36abefc6` |
| --- | --- | --- |
| claim | +5.1 pp pooled (CI [−0.5, +10.7], p=0.065); **+9.8 pp single-hop, n=41 (CI [+2.4, +19.5], p=0.048)** | **no arm beats `base` at FDR q<0.05** |
| gate | hybrid abstains 10.2 pp less | marginal value over never-escalating **+2.5 pp, p=0.549** |
| cost | $0.148 vs $0.165 per suite | forced escalation is pure cost: **3.71× median latency**, replicated in both draws |

Conditions line under the table: 98 questions × 5 public scenarios, independent judge
`kimi-k2.5` (different model family from the generators), position-swapped pairwise,
8/8 canary self-test, numbers measured on a 2-core/CPU-fallback sandbox, not this workstation.
Then the sentence that buys credibility: *"A single Layer-2 draw is not a finding — re-running
the four M11 arms a day apart flipped `oracle-gate`'s delta from −3.6 pp to +2.5 pp."*
Then one line pointing at `docs/benchmarking.md` for metric definitions and
`docs/results.md` for the full record, plus the reproduce commands.

`README.md:157-170` ("What makes it different") is rewritten to describe **mechanism and
cost** — recovery on the hard path, citation verification, what each adds and what it buys in
latency — and cites the null. It no longer asserts the hybrid is more correct.

## 5. New page specification

### `docs/usage.md`

Task-shaped, each task self-contained with what you click and what you see.

- **Add documents** — 11 accepted extensions; `≤25 MiB/file`, `≤10 files/request`
  (`routes.py:28-29`); per-file error rows rather than a failed request; `processing → ready
  → error` with hover for the exception; **no reindex exists** — changing `chunk_size` or the
  embedder means delete + re-upload, and the documented nuclear reset is `rm -rf backend/data`
  (`setup.md:257`).
- **Ask** — Enter sends, Shift+Enter newline; 1–8000 chars (`schemas.py:12`) with a note that
  exceeding it surfaces as an opaque red 422 box; follow-ups work but **only the last 8
  messages are replayed as history** (`pipelines.py:928-950`).
- **Choose a mode** — as §4.7.
- **Read an answer** — `[n]` citation chips are clickable and open the trace; groundedness
  badge = Jev P(supported), **hybrid-only**; quality badge = `0.4·answers_request +
  0.4·citations_supported + 0.2·no_contradiction` (`chat-message.tsx:55-73`); effort chip; the
  escalation decision lives in the trace card "Escalation gate (score features)", not in the
  bubble.
- **Read the trace panel** — its six sections, and that **it is not copyable** today
  (the only clipboard affordance in the app is "Copy status JSON", `status-pill.tsx:120-135`).
- **Run the Benchmark Lab** — click path, the 11 shipped scenarios (6 internal / 48 Q +
  5 public / 98 Q, all committed, no downloads), what each dashboard card means, one run at a
  time per process (409 otherwise), and that the UI only offers delete on a **completed** run
  (`bench-view.tsx:93`) so cancel is unreachable from the browser.
- **Corpus contamination warning** — a full lab run re-ingests ~779 `bench-*.md` documents
  through the same `Ingestor` into the same Chroma collection (`runner.py:343-383`), and chat
  never filters `doc_ids` (`pipelines.py:229-231`), so your next answer can be grounded in the
  benchmark corpus. Recommend a separate `JEVRAG_DATA_DIR` for lab work.
- **Known gaps** — stated as a list, not hidden: cannot stop a stream (the send button shows a
  stop glyph that is disabled and unwired, `chat-panel.tsx:209-214`), no copy-answer, no
  export, no delete-all, no settings screen, history capped at 100 conversations with no
  pagination.

### `docs/configuration.md`

- Opening contract: env-only, read **once at startup**, restart required, `backend/.env.example`
  is the template.
- Tables grouped by *why you'd touch it*: required (2) · models · retrieval depth · hybrid
  gate & slots · memory & latency · benchmark.
- Every row: variable, **default in code**, default in `.env.example` where they differ, what
  it does, when to change it, and the cost or risk.
- Must surface the ~25 code-only knobs that appear in neither the template nor any doc
  (`chunk_size=900`, `chunk_overlap=140`, `bm25_k1/b`, `rrf_k=60`, `contextual_prefix`,
  `rerank_mode`, `reranker_model`, `llm_temperature=0.3`, `llm_max_tokens=2000`,
  `disable_llm_thinking`, `jev_enabled`, `retrieval_mode`, the two char limits,
  `jev_decision_timeout`, `embed_cache_dir`, `bench_pairwise`, `lazy_models`).
- Record the price trap: `LLM_PRICES_PER_MTOK` covers exactly two models with
  `DEFAULT_PRICE=(0,0)` (`config.py:26-32`), so swapping `JEVRAG_LLM_MODEL_DEFAULT` makes the
  in-UI cost display `—` until you add a price.
- New `JEVRAG_HOST` and `JEVRAG_FRONTEND_ORIGIN` documented here (§7), including the LAN opt-in.
- Internal-only fields (`doc_ids`, `bench`, `escalate`) listed as **not part of the public chat
  surface** even though the endpoint will accept them.

### `docs/troubleshooting.md`

Symptom-first headings in the user's own words, each with a check and a fix:
"won't start" · "waking local models… forever" · "upload says no extractable text" ·
"N/M file(s) failed to index" · "it cites `bench-*.md` files" · "Local Jev-style engine
unavailable" · "answers are slow" · "cost shows —" · "backend was killed" (the engine
auto-recovers on subprocess death — never remove that) · "can't reach it from another device" ·
"my `.env` change did nothing" · "frontend can't reach the backend".
Links into `setup.md`'s existing 12-row install table instead of duplicating it, and into
`setup-gpu.md` for CUDA/WSL2. Includes the honest note that `/api/system/health` checks
**nothing** (`routes.py:220-222`) and that `/system/status` is the real diagnostic;
logs live on stdout, in `logs/backend.log` when self-spawned, and `dev.log` for the frontend.

### `docs/README.md`

Three lanes, one "which doc do I need right now" line per lane, one line on what each page is
for, and a pointer to `CONTRIBUTING.md` + `docs/dev/` for maintainers. No design rationale.

Style for all four: sentence-case headings, second person, contractions permitted, action
headings start with a base verb, alt text on every image, no links inside headings
(Google developer documentation style guide).

## 6. Claims and accuracy corrections

| Current | Evidence | Replacement |
| --- | --- | --- |
| `0` fabrications (`README.md:18`) | metric denominator is unanswerable questions, which exist only in `outofscope` (n=5); zeros come from v2 `bf05f585` / v1 `9d894b6c`; `0314ac0a` measured 20 % (1/5) on the same 5; the current record says "fabrication-risk side is untested here" | "Fabrication is measured only on the 5 unanswerable questions of the `outofscope` scenario: 0/5 in the last two internal runs (v2 pipeline). **Not re-measured on v3.**" + link to `benchmarking.md` |
| hybrid wins on hard questions (`README.md:157-170`) | `36abefc6`: no arm beats base at q<0.05 | mechanism + cost, citing the null (§4.9) |
| ~2 GB disk (`README.md:53`) | `setup.md:33` 5 GB min / 8 GB comfortable | the setup numbers, one place |
| ~10 min vs ~15 min (`setup.md:74` vs `:3`) | same file | one number, stated once |
| GGUF `~505 MB` / `0.53 GB` / `529,296,864 B` | same file, three roundings | `0.53 GB (529,296,864 B)` everywhere |
| `README.md#configuration-backendenv` (`setup.md:97`) | anchor never existed | link to the new `docs/configuration.md` |
| `JEVRAG_GATE_SCORE_THRESHOLD` `0.6` vs `0.5` | `.env.example:54` vs `config.py:134` | §7 |
| "Fully local stack" (`page.tsx:196`) | a Cloud status dot is on the same page | accurate footer copy |
| remote favicon (`layout.tsx:25`) | third-party URL in a local-first app | local `public/logo.svg` |

## 7. Behavior changes

1. **`JEVRAG_HOST`, default `127.0.0.1`.** New field in `app/config.py` resolved like every
   other path/setting (CWD-independent). Read by `app/main.py:124` + its docstring,
   `scripts/dev.sh:21` and `scripts/backend_service.sh:19`. `ensure-backend` spawns
   `backend_service.sh` (`route.ts:22,47`) and health-checks `http://127.0.0.1:8000`
   (`route.ts:20`), so the self-healing path keeps working on loopback. LAN use = set the var,
   documented in `configuration.md` and `troubleshooting.md`.
2. **CORS narrowed** from `["*"]` to the frontend origin, configurable via a new
   `JEVRAG_FRONTEND_ORIGIN` (default `http://localhost:3000` and `http://127.0.0.1:3000`).
3. **`JEVRAG_GATE_SCORE_THRESHOLD` default → `0.6`** in `config.py`, matching `.env.example`
   and the published θ=0.6 calibration operating point of the `base` arm. Users who never
   copied the template currently get a different, less-calibrated gate than the docs describe.
4. **Local favicon** + **footer copy** fix.
5. **`backend/.env.example` gains both new vars** (`JEVRAG_HOST`, `JEVRAG_FRONTEND_ORIGIN`) in
   the same commit — the root AGENTS.md contract is that the template stays current with every
   config change. `docs/setup.md:149` also currently *teaches* the expected output as
   "Uvicorn running on `http://0.0.0.0:8000`", so it is updated to the loopback line or the
   docs will contradict the shipped default on day one.

Contract triggered: changing a Jev gate knob means the root AGENTS.md "benchmarks guard the
pipelines" rule applies — a bench smoke run (`POST /api/bench/runs`, one scenario) with the
delta versus `docs/benchmark-results.md` recorded in that commit message.

New hermetic tests: default bind is loopback; `"*"` is absent from the CORS origins; the gate
default equals the `.env.example` value.

Out of scope by decision: stripping `doc_ids` / `bench` / `escalate` from the public chat
endpoint (`routes.py:51-52` parses the full model) — documented as internal, not hardened.

## 8. Visual work

- **Social preview**: regenerate at 1280×640, **under 1 MB** (GitHub's documented cap), and fix
  `render_social_preview.py` to derive its output path from the repo root like every other
  script.
- **Mermaid**: delete the `%%{init …}%%` dark-theme block and the 15 `style` lines so GitHub's
  own theme applies; shrink to one lane ≤15 lines; add `accTitle`/`accDescr`.
- **Screenshots**: one hero only; `chat-compare.png` stops appearing twice; alt text kept on
  all.
- **Dead assets removed** (zero references anywhere in tracked files):
  `escalation-gate.png` (1.80 MB), `v3-architecture-diagram.png` (1.81 MB), `v2-multistep.png`
  (0.15 MB), `v2-trace-panel.png` (0.14 MB) — 3.9 MB of 6.7 MB. Kept: `banner.svg`,
  `chat-compare.png`, `trace-panel.png`, `bench-lab.png`, `bench-charts.png`,
  `layer2-arm-results.png`, `social-preview.png`, the three `-v2` diagram PNGs + their `.mmd`
  and `.svg` siblings, and `generate_diagrams.py`.
- `docs/AGENTS.md` `assets/img/` ownership updated to drop the `v2-*.png` mention.
- Explicitly declined: a demo GIF (needs live browser capture, out of the chosen scope) and
  `#gh-*-mode-only` image pairs (the app is dark-theme-styled; a light-mode screenshot would be
  a mock, which the DOX forbids).

## 9. Repo tidying

- **`docs/dev/`** holds `worklog.md` and `project-status-2026-09-30.md` plus a child
  `AGENTS.md` (Purpose: raw per-task log and dated snapshots; not durable contracts) and a
  `README.md` line telling readers why these exist. Every inbound reference is repaired:
  `docs/jev-improvements-research.md` (lines 11, 109, 128, 189), `docs/windows-setup.md:380`,
  `docs/rag-upgrade-2026-results.md:90`, `CHANGELOG.md:10` and `:59`, `AGENTS.md:92`,
  `backend/app/rag/crossenc.py:19`, `backend/scripts/run_testbench.py:160` — plus the moved
  files' own links, which now point *out* of `docs/dev/` (`../worklog.md` → `worklog.md`, and
  `docs/…` → `../…` for project-status's references to the durable docs).
  `scripts/check_docs_links.sh` (§11.1) is what proves none were missed.
- **`.github/dependabot.yml`** for npm, pip, and github-actions (weekly) and
  **`.github/release.yml`** for categorized auto-generated release notes — both on GitHub's
  own 2026 maintainer checklist.
- **`.github/ISSUE_TEMPLATE/`**: add a "Setup / install problem" template routing to
  `troubleshooting.md`; update `config.yml` contact links to the docs hub and the new pages.
- **Skipped**: `CODE_OF_CONDUCT.md` (research: none of ollama, Dify, khoj, AnythingLLM,
  RAGFlow or txtai foregrounds it; noise for a small research repo — reverses the default in the
  approved "Tidy" option) · `FUNDING.yml` · `llms.txt` (built for docs sites, not a repo tree).
- **Manual, cannot be done from files**: enabling **private vulnerability reporting**.
  `SECURITY.md:12` already directs reporters there. Settings → Security & insights →
  Report a vulnerability. Its scope note is also updated for the new loopback default.
- **Untouched**: root `Caddyfile`, the gitignored scratch files, `CHANGELOG.md` structure.

## 10. Out of scope

App UI redesign · demo GIF/video · hosted docs site · `docs/` file renames · stopping/aborting
streams, copy-answer, export, bulk delete, settings screen (each is a feature, not a doc) ·
hardening the internal chat fields · any retrieval/prompt/pipeline change.

## 11. Verification gates, in order

1. `scripts/check_docs_links.sh` (new, durable, CI job #3): every relative markdown link
   resolves on disk **and** every `#anchor` is validated against GitHub's documented anchor rules
   (lowercase, spaces→hyphens, markup stripped, duplicates suffixed). Chosen over a one-off
   check because anchor rot has already shipped twice.
2. `cd backend && .venv/bin/python -m pytest tests -v` — green, including the three new tests.
3. `bun run lint` — green.
4. Bench smoke (`POST /api/bench/runs`, one scenario) with the delta versus
   `docs/benchmark-results.md` in the commit message — required by the gate-default change.
5. Live browser (`src/AGENTS.md` makes this mandatory): favicon, footer copy, both modes,
   compare, upload, trace panel, no horizontal overflow at mobile width.
6. Rendered-output caveat: social preview and GitHub anchor behavior are only *confirmable*
   post-push; before that they are validated against GitHub's published rules.
7. DOX pass in the same commits: `docs/AGENTS.md` (new pages, `docs/dev/`, an ownership line for
   `superpowers/specs/` — dated design specs, one per brainstorm, not user-facing — and the
   trimmed asset list), `docs/dev/AGENTS.md`, root `AGENTS.md` (child index + the user-layer
   contract), `backend/AGENTS.md` (config default), `scripts/AGENTS.md` (link checker,
   social-preview path), `src/AGENTS.md` (favicon/footer), plus a CHANGELOG entry.
8. All commands run under `wsl -d Ubuntu-24.04 -- bash -ic "…"`. Push only with explicit
   confirmation, and from WSL (the SSH key lives in WSL; Windows Git Bash fails on publickey).
   `scripts/dev.sh` and `scripts/backend_service.sh` are among the always-phantom-dirty
   `scripts/*.sh` files, so stage explicitly and diff before staging.

## 12. Success criteria

- A first-time user can go from clone to a cited answer using only README + `setup.md`, with
  no number in either contradicting the other.
- `docs/README.md` answers "which doc do I need" for all 22 content docs; no orphan.
- Every claim about correctness, cost, latency, fabrication, disk, and binding in the README is
  traceable to a run id, a file:line, or a documented default.
- The README's privacy sentence is true of the shipped default (`127.0.0.1`, CORS not `*`).
- `check_docs_links.sh` exits 0 and fails when an anchor or path is broken (verified by
  deliberately breaking one).
- No tracked file path outside `docs/dev/` changed; every pre-existing doc URL still resolves.

## 13. Sources

- GitHub: [About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes) ·
  [Mermaid diagrams](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/creating-diagrams) ·
  [Social media preview (1 MB, 1280×640)](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview) ·
  [Theme-context images](https://github.blog/changelog/2021-11-24-specify-theme-context-for-images-in-markdown/) ·
  [Large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) ·
  [Dependabot quickstart](https://docs.github.com/en/code-security/getting-started/dependabot-quickstart-guide) ·
  [Auto-generated release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes) ·
  [Issue templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository) ·
  [6 security settings every maintainer should enable](https://github.blog/security/6-security-settings-every-github-maintainer-should-enable-this-week/) ·
  [Private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
- README practice: [standard-readme spec](https://github.com/RichardLitt/standard-readme/blob/main/spec.md) ·
  [GitHub community: what makes a README excellent](https://github.com/orgs/community/discussions/176605) ·
  [docsio README examples 2026](https://docsio.co/blog/readme-examples) ·
  [badge best practices](https://daily.dev/blog/readme-badges-github-best-practices/) ·
  [Utrecht: README files for reproducible code](https://utrechtuniversity.github.io/workshop-computational-reproducibility/chapters/readme-files.html)
- Repo surveys: [ollama](https://github.com/ollama/ollama) ·
  [RAGFlow](https://github.com/infiniflow/ragflow) · [Dify](https://github.com/langgenius/dify) ·
  [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) ·
  [khoj](https://github.com/khoj-ai/khoj) · [mem0](https://github.com/mem0ai/mem0) +
  [memory-benchmarks](https://github.com/mem0ai/memory-benchmarks) ·
  [LightRAG](https://github.com/HKUDS/LightRAG) · [txtai](https://github.com/neuml/txtai) ·
  [Jan](https://github.com/janhq/jan) · [Open WebUI](https://github.com/open-webui/open-webui) ·
  [DeepSeek-V3 eval footnotes](https://github.com/deepseek-ai/DeepSeek-V3)
- Writing: [Diátaxis](https://diataxis.fr/) · [Divio system](https://docs.divio.com/documentation-system/) ·
  [Google style: headings](https://developers.google.com/style/headings) ·
  [person](https://developers.google.com/style/person) ·
  [contractions](https://developers.google.com/style/contractions) ·
  [docguide Markdown style](https://google.github.io/styleguide/docguide/style.html) ·
  [GitBook documentation structure](https://gitbook.com/docs/guides/docs-best-practices/documentation-structure-tips) ·
  [Mermaid accessibility](https://mermaid.ai/open-source/config/accessibility.html) ·
  [emoji anchor breakage](https://github.com/thlorenz/anchor-markdown-header/issues/36)
- Docs frameworks: [Material for MkDocs maintenance-mode notice](https://squidfunk.github.io/mkdocs-material/blog/) ·
  [issue #8523](https://github.com/squidfunk/mkdocs-material/issues/8523) ·
  [pkgpulse best documentation frameworks 2026](https://www.pkgpulse.com/guides/best-documentation-frameworks-2026)

Unverified and not relied upon: the "1200×300 hero banner" convention, the literal "run in 60
seconds" framing, and a 25 MB issue-attachment ceiling (community-reported only).
