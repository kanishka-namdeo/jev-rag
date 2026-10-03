# Configuration

Every tunable in Jev-RAG is an environment variable with the prefix `JEVRAG_`, read from
`backend/.env` (copy the template [../backend/.env.example](../backend/.env.example) to
start). This page lists the whole settings surface — all 65 fields of
[../backend/app/config.py](../backend/app/config.py) — with the real defaults dumped from
the code, when you'd touch each knob, and what it costs you.

## How settings work

- **Env only.** Nothing is configured through the UI or a config file besides `backend/.env`.
  Variable names are `JEVRAG_` + the field name in upper snake case.
- **Read once at startup.** Settings are loaded a single time when the backend boots and
  cached. **Restart the backend after every edit** — nothing hot-reloads.
- **Relative paths anchor to the repo root**, not to the directory you launched from.
  `JEVRAG_DATA_DIR=./backend/data` means `<repo>/backend/data` whether you start the server
  from the repo root or from `backend/`. Absolute paths work too.
- **The template is the supported subset.** `backend/.env.example` carries 36 active lines
  plus 3 commented examples; the remaining 25 settings exist only in code (see
  "Knobs not in the template"). Anything you add to `.env` is read the same way.
- **Unknown variables are ignored**, so a stale typo in `.env` fails silently — check the
  startup log line `settings loaded: ...` if something doesn't take effect.

Defaults below are dumped from `Settings.model_fields` on the current code. Booleans are
written the way the template writes them (`true` / `false`).

## Required

Two variables, and you must set both — the app has no key baked in.

| Variable | Default | What it does | Change it when | Cost / risk |
| --- | --- | --- | --- | --- |
| `JEVRAG_DASHSCOPE_BASE_URL` | `https://coding-intl.dashscope.aliyuncs.com/v1` | The OpenAI-compatible endpoint that does all generation and judging | Pointing at a different gateway | Every model name this page references must exist on that endpoint; the cost display only knows the built-in price table (see "Cost display") |
| `JEVRAG_DASHSCOPE_API_KEY` | empty — **you must set this** | Bearer key sent to the endpoint above | Once, at setup | Keep it only in `backend/.env` (gitignored); never commit it. [setup.md](setup.md) walks through getting and placing the key |

If your gateway keeps credentials in a rotating file instead of a plaintext key, set
`JEVRAG_DASHSCOPE_AUTH_CONFIG` (see Generation) rather than the two above.

## Models

| Variable | Default | What it does | Change it when | Cost / risk |
| --- | --- | --- | --- | --- |
| `JEVRAG_LLM_MODEL_DEFAULT` | `qwen3.7-plus` | The single cloud generator for both pipelines | Your endpoint has a better or cheaper generator | Unknown model → cost shows `—` ("Cost display"); re-run the benchmark after any generator change; the judge must stay a different model family |
| `JEVRAG_LLM_MODEL_REASONING` | `qwen3.6-plus` | Legacy v1 "deep-reasoning route". v2 generation does not route to it; it still feeds the price table and is recorded in system status and bench configs | Almost never | Keeping it off the endpoint's model list only makes status output misleading |
| `JEVRAG_JEV_MODEL_DIR` | `./models/jev-style` | Where the local 0.8B decision model (System One) GGUF files live | Storing models on another disk | Wrong path → engine fails to load; hybrid mode becomes unavailable with a clear error (the app degrades to traditional mode, it never crashes) |
| `JEVRAG_JEV_QUANT` | `Q4_K_M` | Which quantized GGUF file to load from the model dir | You downloaded a different quant | Larger quants cost RAM/VRAM; the file must actually exist in the dir |
| `JEVRAG_JEV_SCORER` | unset (empty) | Path to the `jev-score` scorer binary. Unset means the runtime's own lookup finds it — `scripts/setup_local_models.sh` builds it at `models/jev-style/build/jev-score` | You built or moved the binary somewhere the lookup misses | A wrong path → engine load failure → hybrid unavailable. The opt-in template line is commented out on purpose; leave it unset unless the lookup fails |
| `JEVRAG_EMBED_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | The local ONNX embedding model (fastembed) used for all dense retrieval | Switching to English-only (`BAAI/bge-small-en-v1.5` is lighter) or a bigger encoder | See "Model swaps" — changing this means re-embedding every document |
| `JEVRAG_RERANKER_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | The ONNX cross-encoder that scores each candidate; its top-1 score feeds the escalation gate | Needs more multilingual rerank quality | The gate threshold `0.6` is calibrated for **this** reranker's scores — swapping it invalidates the calibration and run-to-run benchmark comparability |
| `JEVRAG_BENCH_JUDGE_MODEL` | `kimi-k2.5` | The LLM-as-judge for benchmark runs | Rarely | Must stay model-family-independent from the generator (qwen3.x-plus) to avoid self-preference bias; changing it breaks comparison with every published result — the contract is in [../backend/AGENTS.md](../backend/AGENTS.md) |

## Generation

| Variable | Default | What it does | Change it when | Cost / risk |
| --- | --- | --- | --- | --- |
| `JEVRAG_LLM_TEMPERATURE` | `0.3` | Sampling temperature for cloud generation | You want looser prose or stricter grounding | Higher temperatures drift more; benchmark results stop being comparable run-to-run |
| `JEVRAG_LLM_MAX_TOKENS` | `2000` | Output cap per answer | Answers get cut off (or you want cheaper replies) | Output tokens are the expensive half of the bill; lowering it truncates long cited answers |
| `JEVRAG_DISABLE_LLM_THINKING` | `true` | Asks the endpoint to strip chain-of-thought from responses (retries without the flag if a gateway rejects it, then filters `reasoning_content` deltas) | You want to see the model's reasoning | Turning it off raises latency and output cost; best-of-2 deliberately runs one candidate with thinking on regardless of this knob |
| `JEVRAG_DASHSCOPE_EXTRA_HEADERS` | empty (code only) | Extra request headers as a JSON object string, for gateways with ad-hoc header needs | A gateway demands a header the client doesn't send by default | Must be valid JSON; ignored entirely when `JEVRAG_DASHSCOPE_AUTH_CONFIG` is set |
| `JEVRAG_DASHSCOPE_AUTH_CONFIG` | empty | Path to a gateway auth file (JSON with `baseUrl`/`apiKey`/`token`, z-ai-web-dev-sdk style). When set it **overrides** base URL and API key and injects the `X-Token` headers those gateways require | Your credentials live in a managed file that rotates | Silently replaces the two Required vars; an unreadable file means you're pointing at the wrong gateway |

## Retrieval

| Variable | Default | What it does | Change it when | Cost / risk |
| --- | --- | --- | --- | --- |
| `JEVRAG_TOP_K_RETRIEVE` | `10` | How many candidate passages the hybrid search pulls before reranking | Shallow searches miss the gold passage / you want faster answers | Each extra candidate costs a cross-encoder pass on CPU — linear latency |
| `JEVRAG_TOP_K_USE` | `4` | How many reranked passages actually go into the LLM prompt | Answers say "not enough context" though the KB has it / prompts feel bloated | Prompt tokens grow near-linearly (real money on long chunks); past a point extra passages dilute and hurt precision |
| `JEVRAG_RETRIEVAL_MODE` | `hybrid_rrf` (code only) | `hybrid_rrf`: BM25 ‖ dense fused with reciprocal-rank fusion. `dense`: embedding-only, the pre-v3 fallback arm | Testing whether the BM25 lane helps your corpus | `dense` measurably loses keyword recall; either non-default value makes published retrieval results inapplicable ([rag-upgrade-2026.md](rag-upgrade-2026.md)) |
| `JEVRAG_RERANK_MODE` | `cross` (code only) | The rerank slot used by **both** pipelines: `cross` (ONNX cross-encoder), `jev` (local Jev noul, pre-v3), `none` (passthrough — testbench arms) | Benchmarking the rerank contribution | The `features` gate reads cross-encoder scores; `jev`/`none` make the escalation gate meaningless — pair with `JEVRAG_GATE_MODE` |
| `JEVRAG_RERANK_CHAR_LIMIT` | `0` | Characters of each chunk scored by the cross-encoder; `0` = full chunk text (the CE truncates at its own 512-token window). Separate from `JEVRAG_JEV_RERANK_CHAR_LIMIT` since 2026-10-03 — the jev latency knob used to throttle the CE to 400 chars | You have evidence rerank quality moves with passage length | Narrowing blinds the reranker (and the gate's top-1 feature) to evidence past the cutoff |
| `JEVRAG_BM25_K1` | `1.5` (code only) | Okapi BM25 term-frequency saturation | Corpus-specific IR tuning | Re-run the Layer-1 retrieval benchmarks before trusting a tuned value |
| `JEVRAG_BM25_B` | `0.75` (code only) | Okapi BM25 length normalization | Same as above | Same |
| `JEVRAG_RRF_K` | `60` (code only) | Reciprocal-rank-fusion constant blending the two result lists | Rarely — it's the standard value | Same |
| `JEVRAG_CHUNK_SIZE` | `900` characters (code only) | Splitting granularity at ingestion | Very short documents / you want tighter citation spans | **Only affects new uploads** — existing chunks keep their old size. A real change means deleting and re-uploading the corpus |
| `JEVRAG_CHUNK_OVERLAP` | `140` (code only) | Characters repeated between adjacent chunks | Answers keep splitting a sentence across chunks | More overlap = more storage and more near-duplicate passages competing in rerank |
| `JEVRAG_CONTEXTUAL_PREFIX` | `true` (code only) | Prepends "doc title \| section" to each chunk before embedding (Anthropic contextual-retrieval pattern) | Untitled, flat corpora where the prefix adds noise | Turning it on/off changes the vectors — re-ingest; the documented evidence had top-20 retrieval failures drop 5.7% → 3.7% on their eval |

## Hybrid pipeline and escalation gate

Each flag here maps to one researched decision slot in the hybrid pipeline. They apply to
**hybrid mode** (and the gate to escalation into the hard path); traditional mode ignores them.

| Variable | Default | What it does | Change it when | Cost / risk |
| --- | --- | --- | --- | --- |
| `JEVRAG_GATE_MODE` | `features` | Decides easy vs hard path: `features` compares the top-1 cross-encoder score to the threshold below (the score is monotone in relevance, not a calibrated probability — only the threshold operating point is calibrated); `jev` uses the old absolute Jev sufficiency probability (`JEVRAG_JEV_SUFFICIENCY_THRESHOLD`); `none` never escalates | Benchmarks (arms), or experimenting with gate strategies | `jev` mode is the pre-v3 design the published literature contradicts for zero-shot 0.5B models — don't ship it based on intuition |
| `JEVRAG_GATE_SCORE_THRESHOLD` | `0.6` | The score cutoff in `features` mode. Provenance: Layer-1's Youden optimum was 0.987 (rejected — would escalate 47% for +1.1pp gate accuracy); 0.6 is the cost-capped operating point that escalates ~17–19% concentrated on hard scenarios. Layer-1's write-up once concluded 0.5 while the template already said 0.6; 2026-10-01 aligned code to the template | You want more/fewer hard-path escalations | Lower → more escalations (slower, more cloud tokens); higher → more easy-path answers, more ungrounded ones. All published gate-calibration tables in [testbench-results-layer2-full9.md](testbench-results-layer2-full9.md) are computed at 0.6. Check an old `.env` doesn't pin a stale value (see "Known template drift") |
| `JEVRAG_JEV_SUFFICIENCY_THRESHOLD` | `0.5` (code only) | The cutoff used only when `GATE_MODE=jev` | Tuning the legacy gate | No effect in the default `features` mode |
| `JEVRAG_HYBRID_EFFORT_ROUTING` | `true` | Slot [1]: the local model chooses `no_retrieval` / `single_pass` / `multi_step` per question (~1.2 s of decision time) | Speeding up every answer by removing the decision | Losing routing sends everything down one path; the decision is what keeps look-up questions off the no-retrieval fast path |
| `JEVRAG_JEV_NO_RETRIEVAL_THRESHOLD` | `0.9` | Retrieval is skipped only when P(no_retrieval) ≥ this | Trusting the fast path more often | Measured: at 0.5 the fast path misrouted a look-up policy question and answered an unanswerable question from parametric knowledge (bench run 0314ac0a). Validated chat questions score ≥ 0.94, so 0.9 keeps chat fast while defaulting factual questions to retrieval. Lower it only if you're sure |
| `JEVRAG_HYBRID_MULTISTEP` | `true` | For `multi_step` routes: decompose the question, retrieve per sub-query, merge | Simple-corpus setups where decomposition is overkill | Decomposition adds one LLM call plus per-subquery retrieval |
| `JEVRAG_JEV_MULTISTEP_SUBQUERY_K` | `6` | Chunks retrieved per sub-query before the merge | Deep multi-hop questions still miss evidence | More chunks → bigger rerank pool → more CPU rerank time |
| `JEVRAG_JEV_MULTISTEP_MAX_POOL` | `12` | Cap on the deduped pool fed into the reranker | Same trade-off as above | Same |
| `JEVRAG_HYBRID_PASSAGE_BATTERY` | `false` | Slot [2]: per-passage evidence/conflict/injection screening before generation | You've calibrated per-corpus thresholds and want aggressive filtering | Measured ON-default cost (bench run 0314ac0a, 48 questions): the injection signal fired 0.91–0.98 on ordinary earnings/technical prose (25 drops, 8 of them gold passages), evidence collapsed to ~0.03 on near-duplicate corpora → 39.5% over-abstention, correctness −20.8 pp vs traditional (Wilcoxon p = 0.033). Absolute-threshold gating needs per-corpus calibration before shipping on |
| `JEVRAG_JEV_INJECTION_DROP_THRESHOLD` | `0.9` | Battery (when on): drop a passage when P(prompt injection) ≥ this | Untrusted documents in the KB | Lower values drop innocent prose — see the measurement above |
| `JEVRAG_JEV_CONTRADICTION_BLOCK_THRESHOLD` | `0.5` | Battery (when on): block a passage pair when P(contradiction) ≥ this; blocked passages move to a flagged prompt section and keep their citation labels | You want conflict filtering earlier | More blocks → more content moves out of the main context |
| `JEVRAG_JEV_EVIDENCE_DROP_THRESHOLD` | `0.1` | Battery (when on): drop when P(evidence) < this **and** rerank relevance < 0.5 | Aggressive cleanup of weak passages | The relevance ≥ 0.5 rescue is what stops it dropping useful-but-quiet passages |
| `JEVRAG_HYBRID_CORRECTIVE_RETRY` | `true` | Slots [3/4]: if the hard path still says "insufficient", rewrite the query and re-retrieve (one retry) | Cutting worst-case latency | One extra retrieval + rewrite only on failed-looking answers — near-free on the happy path |
| `JEVRAG_HYBRID_BEST_OF_N` | `true` | Slot [5]: generate two candidates (thinking off/on) concurrently and let the local model pick | Halving hard-path cost | Two cloud generations per hard-path answer — this is the biggest bill knob here |
| `JEVRAG_HYBRID_CITATION_VERIFY` | `true` | Slot [6]: check each citation supports / contradicts / says nothing about its sentence | When you can tolerate unverified citations for speed | One extra Jev decision per citation |
| `JEVRAG_JEV_CITATION_CONFIDENCE` | `0.8` | A citation check with confidence ≥ this is auto-accepted (skips escalation to the slower handling) | You want stricter citation auditing | Lower → more citations auto-trusted |
| `JEVRAG_HYBRID_VERIFY_ANSWERS` | `true` | Post-answer groundedness check (Jev noul) that produces the verification badge in the UI | Removing the last local check for latency | Without it the trace panel and message badge lose the groundedness signal; the check is best-effort and degrades silently |

## Memory and latency

These control the local `jev-score` subprocess and pacing. The engine needs roughly 1.5 GB
RSS with the defaults below; on a small machine this group is where you tune.

| Variable | Default | What it does | Change it when | Cost / risk |
| --- | --- | --- | --- | --- |
| `JEVRAG_JEV_ENABLED` | `true` (code only) | Master switch for the local System One engine | Freeing ~1.5 GB of RAM / running traditional-only | Off → hybrid mode reports unavailable; every Jev-dependent slot in the tables above stops working |
| `JEVRAG_JEV_DECISION_TIMEOUT` | `120.0` seconds (code only) | Per-call timeout for a decision subprocess before it's considered dead | Very slow machines where decisions legitimately take longer | Higher = a wedged subprocess ties up a chat request longer; the engine auto-respawns after subprocess death |
| `JEVRAG_JEV_SCORE_N_CTX` | `8192` | llama.cpp KV-cache context for the scorer. Measured: the stock 32k allocation wastes ~900 MB of KV cache on a capacity never used — Jev states stay under ~3k tokens | You hit context-length errors from unusual giant prompts | Lower → risk of truncation errors; higher → RAM you don't need (it OOM-killed the 4 GB sandbox this project started on) |
| `JEVRAG_JEV_SCORE_N_SEQ_MAX` | `2` | llama.cpp sequence slots. Measured: cutting stock 17 → 2 (with 32 output rows) saves ~306 MB RSS with bit-identical decoding, because exact-mode requests here always run sequentially on sequences 0/1 | You change the runtime to batched fan-out | Wrong value on a batched setup breaks decoding — don't touch without a reason |
| `JEVRAG_JEV_SCORE_N_OUTPUTS_MAX` | `32` | Output-row buffer size — same measurement, paired with the one above | Same | Same |
| `JEVRAG_JEV_RERANK_CHAR_LIMIT` | `400` (code only) | Truncates each passage inside Jev rerank questions — pure latency control on CPU. Since 2026-10-03 this no longer governs the cross-encoder (see `JEVRAG_RERANK_CHAR_LIMIT` above) | Decisions feel slow on your CPU | Longer text per decision = slower System One; the rerank *pattern* stays validated at any length, this only trims it |
| `JEVRAG_JEV_CONTEXT_CHAR_LIMIT` | `1600` (code only) | Truncates the context block fed to the sufficiency/verify decisions | Verification misses evidence sitting further down the context | More truncation → verification can call an answer ungrounded because it literally couldn't see the evidence |
| `JEVRAG_LLM_MIN_REQUEST_INTERVAL` | `0.0` | Minimum seconds between LLM HTTP attempts (initial + retries), shared by generator and judge. `0` disables pacing | A burst-sensitive shared gateway that 429s on retry storms | Measured safe floor for the sandbox's internal gateway: 1.5 s (8/8 judge-sized calls sustained; sub-1.5 s bursts triggered 429 cascades). Generous endpoints like DashScope proper need none — pacing costs you throughput |

## Server and logging

| Variable | Default | What it does | Change it when | Cost / risk |
| --- | --- | --- | --- | --- |
| `JEVRAG_HOST` | `127.0.0.1` | Bind address for the API | You deliberately want other devices on your network to reach the app | **The app has no auth.** `0.0.0.0` hands every LAN device full read/write: conversations, uploads, and deletes. See "Who can reach this" |
| `JEVRAG_PORT` | `8000` | API port | Port 8000 is taken | The frontend proxies `/backend-api/*` to `http://127.0.0.1:8000` by default — if you move the port, also set `JEVRAG_BACKEND_ORIGIN` for the frontend (`next.config.ts`) or the UI loses the backend |
| `JEVRAG_LOG_LEVEL` | `INFO` | Backend log verbosity | Diagnosing a problem | `DEBUG` is noisy but shows pipeline detail; no cost otherwise |
| `JEVRAG_FRONTEND_ORIGIN` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated browser origins allowed to call the API (CORS) | You serve the UI on a different port/host | Wrong list → the browser blocks every call. Deliberately no wildcard: any web page you visit could otherwise drive (and wipe) the local backend |
| `JEVRAG_DATA_DIR` | `./backend/data` | Home of the SQLite DB, ChromaDB vectors, and uploaded files (all gitignored) | Data must live on another disk | Moving it without copying the old contents looks like total data loss. Parallel bench workers each point this at a scratch dir ([parallel-bench-runbook.md](parallel-bench-runbook.md)) |
| `JEVRAG_EMBED_CACHE_DIR` | empty (code only) — defaults to `<data_dir>/fastembed_cache` | Where fastembed stores downloaded embedding weights | Moving models off the repo disk | A wrong path just re-downloads the model; nothing else breaks |
| `JEVRAG_RERANKER_CACHE_DIR` | empty (code only) | Where the ONNX cross-encoder weights cache; empty means the HuggingFace default cache | Airgapped or disk-constrained setups | Same — re-download at worst |

## Benchmarking

Only relevant when you run the Benchmarks lab; defaults match the published methodology in
[benchmarking.md](benchmarking.md).

| Variable | Default | What it does | Change it when | Cost / risk |
| --- | --- | --- | --- | --- |
| `JEVRAG_BENCH_PAIRWISE` | `true` (code only) | MT-Bench position-swap comparison between the two pipelines | Trimming run time | Disabling loses the pairwise evidence every published run reports |
| `JEVRAG_BENCH_CONTEXT_METRICS` | `true` | RAGAS-style context precision/recall — LLM metrics that separate "the evidence wasn't retrieved" from "it was retrieved but ranked low" | Cheaper smoke runs | Adds ~2 LLM calls per question (real cloud cost) |
| `JEVRAG_BENCH_MAX_QUESTIONS_PER_SCENARIO` | `0` (code only) | Question cap per scenario; `0` = all questions | Quick smoke runs | A limited-n run has no statistical power — don't quote its deltas next to full-run numbers |
| `JEVRAG_BENCH_JUDGE_ENSEMBLE` | empty | Comma-separated list of judge models for a multi-judge ensemble (mean for scores, majority vote for labels); empty = single judge | You suspect judge bias in a close comparison | Cost scales with judge count; judges must each stay family-independent from the generator |
| `JEVRAG_BENCH_ROBUSTNESS_PARAPHRASES` | `0` | Generates N paraphrases per question and checks answer/retrieval consistency; `3–5` recommended when used | Measuring pipeline stability | Adds ~N LLM calls per question |

## Knobs not in the template

These 25 settings are real and read from `.env`, but no line exists for them in
`backend/.env.example` — the dump above is the only place to find them. Adding them to the
template is welcome (upstream note, not a blocker: the file's maintainers should track
`config.py`). Everything marked "(code only)" in the tables above is in this group:

- Cloud: `JEVRAG_DASHSCOPE_EXTRA_HEADERS`, `JEVRAG_DISABLE_LLM_THINKING`,
  `JEVRAG_LLM_TEMPERATURE`, `JEVRAG_LLM_MAX_TOKENS`
- Jev engine: `JEVRAG_JEV_ENABLED`, `JEVRAG_JEV_DECISION_TIMEOUT`,
  `JEVRAG_JEV_RERANK_CHAR_LIMIT`, `JEVRAG_JEV_CONTEXT_CHAR_LIMIT`
- Retrieval: `JEVRAG_CHUNK_SIZE`, `JEVRAG_CHUNK_OVERLAP`, `JEVRAG_RETRIEVAL_MODE`,
  `JEVRAG_RERANK_MODE`, `JEVRAG_RERANKER_MODEL`, `JEVRAG_RERANKER_CACHE_DIR`,
  `JEVRAG_BM25_K1`, `JEVRAG_BM25_B`, `JEVRAG_RRF_K`, `JEVRAG_CONTEXTUAL_PREFIX`
- Hybrid: `JEVRAG_HYBRID_VERIFY_ANSWERS`, `JEVRAG_JEV_SUFFICIENCY_THRESHOLD`
- Storage: `JEVRAG_EMBED_CACHE_DIR`
- Bench: `JEVRAG_BENCH_PAIRWISE`, `JEVRAG_BENCH_MAX_QUESTIONS_PER_SCENARIO`
- Not-for-users: `JEVRAG_JEV_SCORE_RLIMIT_DATA_MB`, `JEVRAG_LAZY_MODELS`
  (see "Internal fields you should not set")

Three more appear in the template **commented out** — uncomment only when the note there
applies to you: `JEVRAG_DASHSCOPE_AUTH_CONFIG`, `JEVRAG_JEV_SCORER`,
`JEVRAG_LLM_MIN_REQUEST_INTERVAL`.

## Model swaps

Changing any model name is a bigger deal than changing a threshold:

- **Embedding model** (`JEVRAG_EMBED_MODEL`): must exist in fastembed's supported list and
  download as an ONNX model — an arbitrary Hugging Face name will simply fail to load.
  More importantly, every stored vector was made by the old model: **delete and re-upload
  all documents** afterwards, or (at a different dimension) queries error out and (at the
  same dimension) retrieval silently degrades to noise.
- **Reranker model**: the gate threshold 0.6 is a Youden-J point computed on *this*
  reranker's score distribution. Swap the reranker and re-calibrate before trusting the gate.
- **Judge model**: breaks comparability with every published benchmark result; it also has
  to stay a different model family from both generators ([benchmarking.md](benchmarking.md),
  [../backend/AGENTS.md](../backend/AGENTS.md)).
- **Generator model**: only name a model your endpoint actually serves — the project rule
  is "never invent models" — and expect the cost display to go blank until it has a price
  (next section).

## Cost display

The per-message cost estimate comes from a small hardcoded price table in
[../backend/app/config.py](../backend/app/config.py) (lines 26–32) with exactly two entries:
`qwen3.7-plus` and `qwen3.6-plus` (USD per million input/output tokens, prices verified
2026-09-27). Any other generator makes `estimate_cost_usd` return nothing, and the UI shows
**`—`** instead of a cost. That's a display gap, not a free call. If you swap
`JEVRAG_LLM_MODEL_DEFAULT`, add your model's (input, output) prices to the table in
`config.py` to get the estimates back.

## Who can reach this

Jev-RAG is a single-user, local-first app with **no accounts and no auth**, and one shared
knowledge base — everything any connected client sees, everyone sees. The defaults keep it
on your machine: `JEVRAG_HOST=127.0.0.1` binds loopback only, and
`JEVRAG_FRONTEND_ORIGIN` lists explicit origins (no `*`) so random web pages can't drive
your backend through CORS. Setting `JEVRAG_HOST=0.0.0.0` is an opt-in to share an unauthenticated
read/write/delete API with your whole network — do it only for a machine and network you
trust, and add your UI's origin to the CORS list at the same time.

## Internal fields you should not set

- `JEVRAG_JEV_SCORE_RLIMIT_DATA_MB` (default `0`, off): a heap cap for the scorer child.
  Empirically **not usable** — llama.cpp's repacked weights and graph reservations count
  against `RLIMIT_DATA` far beyond touched RSS, failing "context init failed" even at
  1600 MB while actual RSS is ~1.23 GB. The seq/outputs trims above are the real fix;
  leave this at 0.
- `JEVRAG_LAZY_MODELS` (default `false`, code only): skips eager model loading at startup.
  Exists for the hermetic test suite; leaving it `true` in normal use makes the first real
  request pay for model warm-up.
- `doc_ids`, `bench`, `escalate`: not env vars — request-body fields the chat endpoint
  accepts for its own benchmark runner (retrieval isolation, no-persistence mode, forced
  gate arms). They are not part of the public chat surface and the UI never sends them
  ([api.md](api.md)). Setting anything resembling them in `.env` does nothing.

## Known template drift

- `JEVRAG_GATE_SCORE_THRESHOLD` was **0.5 in code while the template said 0.6** until
  commit `4f7e458` closed the gap — the published calibration tables always assumed 0.6.
  Anyone who skipped the template and ran bare code defaults got a less-calibrated
  escalation gate. Code and template now agree on 0.6; if you copied a very old `.env`
  that hardcodes something else, delete the line or set 0.6 so you run the gate
  [results.md](results.md) describes.
- `JEVRAG_JEV_SCORER` used to be an active template line with a build path while the code
  default was empty. The template line is now commented out — the runtime lookup finds the
  setup-built binary, and an explicit path is opt-in only.
