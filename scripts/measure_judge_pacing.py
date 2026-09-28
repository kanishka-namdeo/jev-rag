#!/usr/bin/env python3
"""measure_judge_pacing.py — can the gateway sustain judge-sized calls?

Simulates the judge self-test: 8 sequential absolute-judging calls with
realistic prompts (~300 tokens) and max_tokens=400, at a configurable interval.
Usage: python3 measure_judge_pacing.py <interval_seconds>
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

INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 1.5

SYSTEM = """You are an impartial evaluation judge for retrieval-augmented generation (RAG) systems.
Score the ANSWER on three dimensions using ONLY what is given:
1. correctness (0.0-1.0): factual agreement with the REFERENCE ANSWER.
2. faithfulness (0.0-1.0): fraction of the ANSWER's claims supported by the RETRIEVED CONTEXT.
3. abstention: "abstained" | "answered" | "fabricated".
Respond with ONLY a JSON object:
{"correctness": <float>, "faithfulness": <float>, "abstention": "answered|abstained|fabricated", "reason": "<one sentence>"}"""

QUESTIONS = [
    ("What is the maximum message size in NimbusDB Pro tier?", "256 MB",
     "NimbusDB Pro tier: messages up to 256 MB; Starter caps at 16 MB.",
     "The maximum message size for the Pro tier is 256 MB."),
    ("What is the retention period for Enterprise tier?", "90 days",
     "Retention: Starter 7 days, Pro 30 days, Enterprise 90 days.",
     "Enterprise retains data for 90 days."),
    ("What is the throughput of the XG200 gateway?", "10 Gbps",
     "The XG200 gateway handles 10 Gbps; XG100 handles 4 Gbps.",
     "The XG200 handles 10 Gbps throughput."),
    ("What SLA does the Pro plan include?", "99.95%",
     "Pro plan SLA: 99.95% monthly uptime. Enterprise: 99.99%.",
     "The Pro plan includes a 99.95% SLA."),
    ("When was Lumen Exhibition founded?", "2011",
     "The Lumen Exhibition was founded in 2011 in Rotterdam.",
     "Lumen Exhibition was founded in 2011."),
    ("What is Northwind's Q3 revenue?", "$142.8 million",
     "Northwind Analytics Q3 revenue was $142.8 million.",
     "Northwind's Q3 revenue was $142.8 million."),
    ("What does the remote-work policy say about core hours?", "10:00-15:00 local time",
     "Remote employees must be reachable during core hours 10:00-15:00 local time.",
     "Core hours are 10:00 to 15:00 local time."),
    ("How many rest days does the travel policy allow?", "1 rest day per 6 consecutive travel days",
     "Employees get 1 rest day per 6 consecutive travel days.",
     "One rest day per six consecutive travel days."),
]

codes = []
latencies = []
t0 = time.time()
print(f"pacing {INTERVAL}s between 8 judge-sized calls (cooling 45s first)...")
time.sleep(45)
for i, (q, ref, ctx, ans) in enumerate(QUESTIONS, 1):
    user = (f"QUESTION: {q}\n\nREFERENCE ANSWER (ground truth): {ref}\n\n"
            f"RETRIEVED CONTEXT:\n{ctx}\n\nANSWER TO EVALUATE:\n{ans}")
    ts = time.time()
    try:
        r = httpx.post(f"{BASE}/chat/completions", headers=H, timeout=60,
                       json={"model": "glm-4-plus",
                             "messages": [{"role": "system", "content": SYSTEM},
                                          {"role": "user", "content": user}],
                             "temperature": 0.0, "max_tokens": 400,
                             "response_format": {"type": "json_object"}})
        codes.append(r.status_code)
        if r.status_code == 200:
            body = r.json()
            ct = body.get("usage", {}).get("completion_tokens", 0)
            print(f"  {i}: {r.status_code} in {time.time()-ts:.1f}s out_tokens={ct}")
        else:
            print(f"  {i}: {r.status_code} :: {r.text[:80]}")
    except Exception as e:  # noqa: BLE001
        codes.append(-1)
        print(f"  {i}: EXC {type(e).__name__}: {e}")
    latencies.append(time.time() - ts)
    time.sleep(INTERVAL)

ok = sum(1 for c in codes if c == 200)
print(f"RESULT: {ok}/8 ok at {INTERVAL}s pacing in {time.time()-t0:.0f}s total; codes={codes}")
