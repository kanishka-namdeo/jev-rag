#!/usr/bin/env python3
"""probe_gateway.py — capability probe for the internal z.ai OpenAI-compatible gateway.

Tests every request shape the Jev-RAG backend sends (dashscope.py + judge.py):
  1. plain completion (temperature, max_tokens)
  2. extra_body enable_thinking=False (qwen-style param)
  3. thinking={"type":"disabled"} (sdk-style param)
  4. streaming with stream_options.include_usage
  5. response_format json_object (judge)
  6. rate-limit probe: 12 sequential calls at bench-like pacing (~1.5s apart)

Auth is read from /etc/.z-ai-config exactly like the z-ai-web-dev-sdk does:
  Authorization: Bearer <apiKey>  +  X-Token: <token>  +  X-Z-AI-From: Z
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

CFG = json.loads(Path("/etc/.z-ai-config").read_text())
BASE = CFG["baseUrl"].rstrip("/")
HEADERS = {
    "Authorization": f"Bearer {CFG['apiKey']}",
    "X-Token": CFG.get("token", ""),
    "X-Z-AI-From": "Z",
    "Content-Type": "application/json",
}
MODEL = "glm-4-plus"  # gateway pins everything here; use canonical name

results: list[tuple[str, str]] = []


def call(name: str, body: dict, timeout: float = 60.0) -> httpx.Response | None:
    try:
        r = httpx.post(f"{BASE}/chat/completions", headers=HEADERS, json=body, timeout=timeout)
        status = r.status_code
        snippet = r.text[:160].replace("\n", " ")
        results.append((name, f"HTTP {status} :: {snippet}"))
        return r
    except Exception as e:  # noqa: BLE001
        results.append((name, f"EXC {type(e).__name__}: {e}"))
        return None


base_msgs = [{"role": "user", "content": "Answer with one word: capital of France?"}]

# 1. plain
call("1-plain", {"model": MODEL, "messages": base_msgs, "max_tokens": 20, "temperature": 0.3})

# 2. enable_thinking extra_body (qwen-style)
call("2-enable_thinking-false", {"model": MODEL, "messages": base_msgs, "max_tokens": 20,
                                 "enable_thinking": False})

# 3. thinking sdk-style
call("3-thinking-disabled", {"model": MODEL, "messages": base_msgs, "max_tokens": 20,
                             "thinking": {"type": "disabled"}})

# 4. streaming + stream_options
try:
    with httpx.stream("POST", f"{BASE}/chat/completions", headers=HEADERS, timeout=60.0,
                      json={"model": MODEL, "messages": base_msgs, "max_tokens": 20,
                            "stream": True, "stream_options": {"include_usage": True}}) as r:
        chunks = []
        usage_seen = False
        content_parts = []
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                break
            d = json.loads(payload)
            if d.get("usage"):
                usage_seen = True
            for ch in d.get("choices", []):
                c = (ch.get("delta") or {}).get("content")
                if c:
                    content_parts.append(c)
            chunks.append(payload[:60])
        results.append(("4-stream+usage", f"HTTP {r.status_code} chunks={len(chunks)} usage_seen={usage_seen} content={''.join(content_parts)!r}"))
except Exception as e:  # noqa: BLE001
    results.append(("4-stream+usage", f"EXC {type(e).__name__}: {e}"))

# 5. response_format json_object
call("5-json-object", {"model": MODEL, "messages": [{"role": "user",
                                                      "content": 'Return JSON: {"verdict":"A","score":1}'}],
                       "max_tokens": 60, "response_format": {"type": "json_object"},
                       "temperature": 0.0})

# 6. rate probe: 12 calls, ~1.2s apart (bench-like pacing)
ok = 0
codes: list[int] = []
t0 = time.time()
for i in range(12):
    r = call(f"6-rate-{i+1:02d}", {"model": MODEL, "messages": [{"role": "user", "content": f"Say the number {i+1}"}],
                                   "max_tokens": 10})
    if r is not None:
        codes.append(r.status_code)
        if r.status_code == 200:
            ok += 1
    time.sleep(1.2)
results.append(("6-rate-summary", f"{ok}/12 ok in {time.time()-t0:.1f}s codes={codes}"))

print("=" * 70)
for name, outcome in results:
    print(f"{name:26s} {outcome}")
print("=" * 70)
