"""Application settings (env-driven, 12-factor style — nothing hardcoded)."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("jevrag.config")

# Verified Dashscope prices (USD per 1M tokens) for cost estimation.
# Sources: llm-stats.com model pages + Alibaba Cloud pricing, verified 2026-09-27.
LLM_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "qwen3.7-plus": (0.32, 1.28),   # (input, output)
    "qwen3.6-plus": (0.50, 3.00),
}
DEFAULT_PRICE = (0.0, 0.0)  # unknown model -> cost shown as n/a


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JEVRAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Cloud LLM (System Two) ---
    dashscope_base_url: str = "https://coding-intl.dashscope.aliyuncs.com/v1"
    dashscope_api_key: str = ""
    # Optional gateway auth file (JSON: baseUrl/apiKey/token, z-ai-web-dev-sdk
    # style, e.g. /etc/.z-ai-config). When set and readable it OVERRIDES
    # dashscope_base_url/dashscope_api_key and injects the X-Token / X-Z-AI-From
    # headers such gateways require. Lets the pipeline run against any
    # OpenAI-compatible gateway whose credentials live in a file (auto-tracks
    # token rotation) instead of plaintext .env values.
    dashscope_auth_config: str = ""
    # Optional extra headers as a JSON object string (escape hatch for gateways
    # with ad-hoc header requirements; ignored when dashscope_auth_config is set).
    dashscope_extra_headers: str = ""
    llm_model_default: str = "qwen3.7-plus"          # the single generator (v2 design)
    # v1 legacy: hybrid used to route hard questions to the reasoning model. The v2
    # pipeline runs ONE generator and spends the saved decision on effort routing /
    # best-of-2 instead (docs/jev-improvements-research.md §1). Kept for price table
    # continuity and as an optional override for best-of-2 candidate B.
    llm_model_reasoning: str = "qwen3.6-plus"        # deep-reasoning route (v1)
    disable_llm_thinking: bool = True                # strip chain-of-thought from answers
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2000
    # Minimum seconds between LLM HTTP attempts (initial + retries), enforced by
    # a shared pacer across generator and judge clients. Burst-sensitive shared
    # gateways (429 without Retry-After) need this to avoid retry death-spirals;
    # 0 disables pacing (fine for generous endpoints like DashScope proper).
    # Measured safe floor for the sandbox internal gateway: 1.5s (8/8 judge-sized
    # calls sustained; sub-1.5s bursts trigger 429 cascades).
    llm_min_request_interval: float = 0.0

    # --- Local Jev-style decision engine (System One) ---
    jev_model_dir: str = "./models/jev-style"
    jev_quant: str = "Q4_K_M"
    jev_scorer: str = ""                # empty -> the runtime's own lookup (JEV_SCORE_BIN)
    jev_enabled: bool = True
    jev_decision_timeout: float = 120.0
    # llama.cpp context for the jev-score subprocess. Stock 32k allocates ~900MB KV
    # cache (sandbox OOM kills); our states stay under ~3k tokens -> 8192 is plenty.
    jev_score_n_ctx: int = 8192
    # llama.cpp per-sequence recurrent state + outputs-row buffer sizing. The runtime's
    # stock flags (17 seq / 256 outputs, ~1,538 MB RSS) size for many_mode="batched"
    # fan-out; our many_mode="exact" requests always run sequentially using only
    # sequences 0/1, so 2/32 cuts ~306 MB (measured) with identical decoding.
    jev_score_n_seq_max: int = 2
    jev_score_n_outputs_max: int = 32
    # RLIMIT_DATA cap (MB) on the jev-score child, opt-in. EMPIRICALLY NOT USABLE:
    # llama.cpp's repacked weights + compute-graph reservations count against the cap
    # far beyond touched RSS (fails "context init failed" even at 1600 MB while actual
    # RSS is ~1.23 GB), so the default is off (0). The flag trim above is the real fix.
    jev_score_rlimit_data_mb: int = 0

    # --- Embeddings (local, ONNX via fastembed) ---
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embed_cache_dir: str = ""           # default: <data_dir>/fastembed_cache

    # --- Storage ---
    data_dir: str = "./backend/data"

    # --- Retrieval / pipeline knobs ---
    top_k_retrieve: int = 10            # candidates pulled from Chroma for hybrid rerank
    top_k_use: int = 4                  # passages actually given to the LLM
    chunk_size: int = 900               # characters
    chunk_overlap: int = 140
    jev_rerank_char_limit: int = 400    # per-chunk truncation inside Jev states (latency control)
    jev_context_char_limit: int = 1600  # context block truncation for sufficiency/verify states
    hybrid_verify_answers: bool = True  # post-answer groundedness check (Jev Noul)

    # --- Hybrid v2 pipeline (single-generator design; docs/jev-improvements-research.md §4) ---
    # With one cloud generator the model-routing slot degenerates into effort routing;
    # every flag below maps to one researched + validated decision slot.
    hybrid_effort_routing: bool = True  # [1] choice {no_retrieval,single_pass,multi_step} (~1.2s)
    jev_no_retrieval_threshold: float = 0.9  # skip retrieval only when P(no_retrieval) >= this.
    # 0.5 -> 0.9 after run 0314ac0a: at 0.5 the fast path misrouted a look-up policy
    # question (p7, automatic loss) and answered an unanswerable question from
    # parametric knowledge (o6, judged fabricated). Validated chat questions score
    # P >= 0.94, so 0.9 keeps the fast path for real chat while defaulting factual
    # questions to retrieval.
    hybrid_multistep: bool = True       # multi_step: decompose -> per-subquery retrieval -> merge
    jev_multistep_subquery_k: int = 6   # chunks retrieved per sub-query before the merge
    jev_multistep_max_pool: int = 12    # deduped pool cap fed into the reranker
    hybrid_passage_battery: bool = False  # [2] per-passage screen: evidence/conflict/injection.
    # OFF by default after full-run evidence (bench run 0314ac0a, 48Q): the battery's
    # injection noul fired 0.91-0.98 on ordinary earnings/technical prose (25 drops,
    # 8 of them gold passages) and its evidence noul collapsed to ~0.03 on near-duplicate
    # KBs (all-4-passage drops) -> over-abstention 39.5%, correctness -20.8pp vs
    # traditional (Wilcoxon p=0.033). Absolute-threshold gating needs per-corpus
    # calibration before it can ship ON; re-enable with JEVRAG_HYBRID_PASSAGE_BATTERY=true
    # and see docs/benchmark-results.md + docs/benchmark-v2-ablation.md.
    jev_injection_drop_threshold: float = 0.9   # drop passage when P(prompt_injection) >= this
    jev_contradiction_block_threshold: float = 0.5  # conflict-block when P(contradiction) >= this
    jev_evidence_drop_threshold: float = 0.1  # drop when P(evidence) < this AND relevance < 0.5
    hybrid_corrective_retry: bool = True  # [3/4] insufficient -> rewrite query -> re-retrieve (1 retry)
    hybrid_best_of_n: bool = True       # [5] 2 candidates (thinking off/on) + Jev selection
    hybrid_citation_verify: bool = True  # [6] per-citation supports/contradicts/says_nothing
    jev_citation_confidence: float = 0.8  # confidence >= this auto-accepts a citation

    # --- Server ---
    port: int = 8000
    log_level: str = "INFO"
    lazy_models: bool = False           # True: skip eager model loading at startup (tests)

    # --- Benchmarking (app.bench) ---
    # Judge model is deliberately INDEPENDENT from both pipelines' generators
    # (qwen3.x-plus): kimi-k2.5 avoids self-preference bias (MT-Bench/G-Eval
    # guidance). Verified: json_object response_format works, ~1.4s/call.
    bench_judge_model: str = "kimi-k2.5"
    bench_pairwise: bool = True         # MT-Bench position-swap comparison
    bench_max_questions_per_scenario: int = 0   # 0 = all questions (smoke runs can limit)

    # --- Derived paths ---
    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def chroma_dir(self) -> Path:
        p = self.data_path / "chroma"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_path / "app.db"

    @property
    def uploads_dir(self) -> Path:
        p = self.data_path / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def fastembed_cache_dir(self) -> Path:
        p = Path(self.embed_cache_dir).expanduser() if self.embed_cache_dir else self.data_path / "fastembed_cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def jev_model_dir_path(self) -> Path:
        return Path(self.jev_model_dir).expanduser().resolve()

    @property
    def jev_scorer_path(self) -> Path | None:
        return Path(self.jev_scorer).expanduser().resolve() if self.jev_scorer else None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logger.info(
        "settings loaded: llm_default=%s llm_reasoning=%s jev_dir=%s embed=%s data=%s",
        settings.llm_model_default, settings.llm_model_reasoning,
        settings.jev_model_dir, settings.embed_model, settings.data_dir,
    )
    return settings
