"""Cloud LLM client (System Two): OpenAI-compatible Dashscope endpoint.

Model roles (verified via llm-stats + Alibaba docs, 2026-09-27):
- qwen3.7-plus: newer, faster, cheaper -> default generation workhorse
- qwen3.6-plus: always-on chain-of-thought, pricier -> deep-reasoning route
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import httpx
from openai import BadRequestError, OpenAI

from app.config import LLM_PRICES_PER_MTOK, DEFAULT_PRICE, Settings

logger = logging.getLogger("jevrag.dashscope")


class _RequestPacer:
    """Thread-safe minimum-interval throttle, applied as an httpx request hook.

    Burst-sensitive gateways (429 without Retry-After) can death-spiral when SDK
    retries arrive faster than the rate-limit window refills: each retry counts
    as a new request and keeps the window saturated. Pacing EVERY HTTP attempt
    (initial calls and retries alike) at a floor interval keeps sustained
    traffic under the limit; requests that already arrive slower than the
    interval pass through without extra delay.
    """

    def __init__(self, min_interval: float):
        self.min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._next_slot = 0.0  # monotonic timestamp of the next free slot

    def hook(self, request: httpx.Request) -> None:  # noqa: ARG002 (signature fixed by httpx)
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.min_interval
            wait = slot - now
        if wait > 0:
            time.sleep(wait)


_PACER: _RequestPacer | None = None
_HTTP_CLIENT: httpx.Client | None = None
_CLIENT_LOCK = threading.Lock()


def _shared_http_client(min_interval: float) -> httpx.Client:
    """One httpx.Client (connection pool + pacer hook) shared by ALL LLM clients
    built in this process, so generator and judge traffic pace together."""
    global _PACER, _HTTP_CLIENT
    with _CLIENT_LOCK:
        if _PACER is None:
            _PACER = _RequestPacer(min_interval)
        if _HTTP_CLIENT is None:
            _HTTP_CLIENT = httpx.Client(event_hooks={"request": [_PACER.hook]})
    return _HTTP_CLIENT


def _load_gateway_auth(settings: Settings) -> tuple[str, str, dict[str, str]] | None:
    """Read the optional gateway auth file (z-ai-web-dev-sdk JSON contract:
    baseUrl / apiKey / token). Returns (base_url, api_key, extra_headers) or
    None when unset/unreadable — callers then fall back to env-based config."""
    path = (settings.dashscope_auth_config or "").strip()
    if not path:
        return None
    try:
        cfg = json.loads(Path(path).expanduser().read_text())
        base = str(cfg.get("baseUrl") or cfg.get("base_url") or "")
        key = str(cfg.get("apiKey") or cfg.get("api_key") or "")
    except (OSError, ValueError) as e:
        logger.warning("dashscope auth config unreadable (%s): %s", path, e)
        return None
    if not base or not key:
        logger.warning("dashscope auth config missing baseUrl/apiKey: %s", path)
        return None
    headers = {"X-Z-AI-From": "Z"}
    if cfg.get("token"):
        headers["X-Token"] = str(cfg["token"])
    logger.info("using gateway auth config %s (extra headers: %s)",
                path, sorted(k for k in headers))
    return base, key, headers


def build_llm_client(settings: Settings, *, timeout: float = 180.0,
                     max_retries: int = 6) -> OpenAI:
    """Construct the OpenAI-compatible client for both generator and judge.

    Precedence: (1) settings.dashscope_auth_config file — overrides base URL /
    API key and injects gateway headers (X-Token / X-Z-AI-From); (2) plain
    dashscope_base_url + dashscope_api_key, plus optional JSON extra headers.
    Retries (default 6, exponential backoff) absorb transient 429s from shared
    gateways that omit Retry-After headers.
    """
    base_url = settings.dashscope_base_url
    api_key = settings.dashscope_api_key or "missing"
    default_headers: dict[str, str] | None = None

    gw = _load_gateway_auth(settings)
    if gw is not None:
        base_url, api_key, default_headers = gw
    elif settings.dashscope_extra_headers.strip():
        try:
            default_headers = json.loads(settings.dashscope_extra_headers)
        except ValueError as e:
            logger.warning("dashscope_extra_headers is not valid JSON: %s", e)

    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
        default_headers=default_headers,
        http_client=_shared_http_client(settings.llm_min_request_interval),
    )


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
        self.client = build_llm_client(settings)

    def stream_answer(
        self,
        *,
        model: str,
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
        enable_thinking: bool | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream an answer. Yields delta events, then a final usage event.

        Qwen "thinking" output (reasoning_content) is suppressed when possible
        via enable_thinking=false; any leaked reasoning deltas are filtered out.
        `enable_thinking` overrides the global setting per call (best-of-2 in the
        v2 pipeline generates a thinking-on candidate this way).
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})

        thinking = self.settings.disable_llm_thinking if enable_thinking is None else not enable_thinking

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
        if thinking is False:
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

    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        enable_thinking: bool | None = None,
    ) -> tuple[str, dict[str, int]]:
        """Non-streaming completion for short utility calls (query rewrite, question
        decomposition, best-of-N candidate sampling).

        Returns (text, usage). Thinking is handled exactly like stream_answer: the
        per-call override wins over the global setting, reasoning_content is never
        returned, and endpoints rejecting enable_thinking are retried without it.
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})

        thinking = self.settings.disable_llm_thinking if enable_thinking is None else not enable_thinking

        def _create(extra_body: dict[str, Any] | None):
            return self.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.settings.llm_temperature if temperature is None else temperature,
                max_tokens=self.settings.llm_max_tokens if max_tokens is None else max_tokens,
                stream=False,
                extra_body=extra_body or {},
            )

        extra_body: dict[str, Any] | None = None
        if thinking is False:
            extra_body = {"enable_thinking": False}
        try:
            resp = _create(extra_body)
        except BadRequestError as e:
            logger.warning("complete: retry without enable_thinking (%s)", e)
            resp = _create(None)

        text = ""
        choice = resp.choices[0] if resp.choices else None
        if choice is not None:
            msg = choice.message
            text = (msg.content or "").strip()
        usage = {
            "prompt_tokens": (resp.usage.prompt_tokens or 0) if resp.usage else 0,
            "completion_tokens": (resp.usage.completion_tokens or 0) if resp.usage else 0,
        }
        return text, usage

    def health(self) -> dict[str, Any]:
        base_url = str(getattr(self.client, "base_url", ""))
        try:
            models = [m.id for m in self.client.models.list().data]
            return {"ok": True, "models": models, "base_url": base_url}
        except Exception as model_err:  # noqa: BLE001 — fall through to chat probe
            # Many OpenAI-compatible gateways do not implement GET /models;
            # probe with a trivial chat completion instead so health reflects
            # what the pipeline actually needs (generation, not catalog).
            logger.info("/models unavailable (%s) — health via chat probe", model_err)
            try:
                resp = self.client.chat.completions.create(
                    model=self.settings.llm_model_default,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5,
                )
                served = getattr(resp, "model", None) or self.settings.llm_model_default
                return {"ok": True, "models": [served], "base_url": base_url,
                        "note": "/models unavailable; verified via chat probe"}
            except Exception as e:  # noqa: BLE001 — health check must never raise
                logger.error("dashscope health check failed: %s", e)
                return {"ok": False, "error": str(e), "base_url": base_url}
