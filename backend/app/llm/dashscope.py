"""Cloud LLM client (System Two): OpenAI-compatible Dashscope endpoint.

Model roles (verified via llm-stats + Alibaba docs, 2026-09-27):
- qwen3.7-plus: newer, faster, cheaper -> default generation workhorse
- qwen3.6-plus: always-on chain-of-thought, pricier -> deep-reasoning route
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterator

from openai import BadRequestError, OpenAI

from app.config import LLM_PRICES_PER_MTOK, DEFAULT_PRICE, Settings

logger = logging.getLogger("jevrag.dashscope")


@dataclass
class StreamEvent:
    type: str                              # delta | usage | done
    content: str = ""
    usage: dict[str, int] = field(default_factory=dict)


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    prices = LLM_PRICES_PER_MTOK.get(model, DEFAULT_PRICE)
    if prices == DEFAULT_PRICE:
        return None
    in_cost = prompt_tokens / 1_000_000 * prices[0]
    out_cost = completion_tokens / 1_000_000 * prices[1]
    return round(in_cost + out_cost, 6)


class DashscopeLLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(
            base_url=settings.dashscope_base_url,
            api_key=settings.dashscope_api_key,
            timeout=180.0,
        )

    def stream_answer(
        self,
        *,
        model: str,
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream an answer. Yields delta events, then a final usage event.

        Qwen "thinking" output (reasoning_content) is suppressed when possible
        via enable_thinking=false; any leaked reasoning deltas are filtered out.
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})

        def _create(extra_body: dict[str, Any] | None):
            return self.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                extra_body=extra_body or {},
            )

        extra_body: dict[str, Any] | None = None
        if self.settings.disable_llm_thinking:
            extra_body = {"enable_thinking": False}
        try:
            stream = _create(extra_body)
        except BadRequestError as e:
            # Some models/endpoints reject the enable_thinking parameter — retry without it.
            logger.warning("retry without enable_thinking (%s)", e)
            stream = _create(None)

        usage: dict[str, int] = {}
        try:
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens or 0,
                        "completion_tokens": chunk.usage.completion_tokens or 0,
                    }
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                content = delta.content
                reasoning = getattr(delta, "reasoning_content", None)  # thinking tokens, not shown
                if reasoning and not content:
                    continue  # pure thinking delta
                if content:
                    yield StreamEvent(type="delta", content=content)
        finally:
            if getattr(stream, "close", None):
                stream.close()
        yield StreamEvent(type="usage", usage=usage)

    def health(self) -> dict[str, Any]:
        try:
            models = [m.id for m in self.client.models.list().data]
            return {"ok": True, "models": models, "base_url": self.settings.dashscope_base_url}
        except Exception as e:  # noqa: BLE001 — health check must never raise
            logger.error("dashscope health check failed: %s", e)
            return {"ok": False, "error": str(e), "base_url": self.settings.dashscope_base_url}
