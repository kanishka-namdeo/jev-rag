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
    llm_model_default: str = "qwen3.7-plus"          # fast, cheap workhorse
    llm_model_reasoning: str = "qwen3.6-plus"        # deep-reasoning route
    disable_llm_thinking: bool = True                # strip chain-of-thought from answers
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2000

    # --- Local Jev-style decision engine (System One) ---
    jev_model_dir: str = "./models/jev-style"
    jev_quant: str = "Q4_K_M"
    jev_scorer: str = ""                # empty -> the runtime's own lookup (JEV_SCORE_BIN)
    jev_enabled: bool = True
    jev_decision_timeout: float = 120.0
    # llama.cpp context for the jev-score subprocess. Stock 32k allocates ~900MB KV
    # cache (sandbox OOM kills); our states stay under ~3k tokens -> 8192 is plenty.
    jev_score_n_ctx: int = 8192

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
