#!/usr/bin/env python3
"""measure_rate_limit.py — characterize the gateway's rate limiter.

Phase A: after a 60s cooldown, 1 call every 4s x 12 (sustained-rate check).
Phase B: 1 call every 2s x 10 (tighter pacing check).
Reports per-call status codes so we can see refill behavior.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

CFG = json.loads(Path("/etc/.z-ai-config").read_text())
BASE = CFG["baseUrl"].rstrip("/")
H = {"Authorization": f"Bearer {CFG['apiKey']}", "X-Token": CFG.get("token", ""),
     "X-Z-AI-From": "Z", "Content-Type": "application/json"}


def call(i: int) -> int:
    r = httpx.post(f"{BASE}/chat/completions", headers=H, timeout=30,
                   json={"model": "glm-4-plus",
                         "messages": [{"role": "user", "content": f"Say {i}"}],
                         "max_tokens": 5})
    return r.status_code


print("cooling down 60s...", flush=True)
time.sleep(60)

print("Phase A: 12 calls @ 4s intervals")
codes_a = []
for i in range(12):
    codes_a.append(call(i))
    print(f"  A{i+1:02d}: {codes_a[-1]}", flush=True)
    time.sleep(4)

print("Phase B: 10 calls @ 2s intervals")
codes_b = []
for i in range(10):
    codes_b.append(call(100 + i))
    print(f"  B{i+1:02d}: {codes_b[-1]}", flush=True)
    time.sleep(2)

ok_a = sum(1 for c in codes_a if c == 200)
ok_b = sum(1 for c in codes_b if c == 200)
print(f"SUMMARY: A {ok_a}/12 @4s   B {ok_b}/10 @2s")
