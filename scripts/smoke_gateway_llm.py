#!/usr/bin/env python3
"""smoke_gateway_llm.py — validate the patched LLM plumbing end-to-end.

Runs INSIDE backend/ (cwd matters: pydantic loads backend/.env). Checks:
  1. Settings load the gateway auth config path.
  2. build_llm_client() reads /etc/.z-ai-config and injects headers.
  3. A streamed generation works (stream_answer path used by pipelines).
  4. Judge absolute() returns parseable JSON scores (response_format path).
"""
from __future__ import annotations

import os
import sys

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
sys.path.insert(0, os.getcwd())

from app.config import Settings  # noqa: E402
from app.llm.dashscope import DashscopeLLM, build_llm_client  # noqa: E402

s = Settings()
print("1. settings: auth_config=%r default=%r judge=%r battery=%s no_ret=%s" % (
    s.dashscope_auth_config, s.llm_model_default, s.bench_judge_model,
    s.hybrid_passage_battery, s.jev_no_retrieval_threshold))

client = build_llm_client(s)
print("2. client: base_url=%s default_headers=%s" % (
    client.base_url, sorted(k for k in (client.default_headers or {}))))

# 3. streamed generation (the pipeline's actual answer path)
llm = DashscopeLLM(s)
parts, usage = [], {}
for ev in llm.stream_answer(model=s.llm_model_default,
                            system="You answer in one short sentence.",
                            user="What is the boiling point of water at sea level?"):
    if ev.type == "delta":
        parts.append(ev.content)
    elif ev.type == "usage":
        usage = ev.usage
print("3. stream: %r usage=%s" % (" ".join(parts)[:120], usage))

# 4. judge call (json_object path)
from app.bench.judge import BenchJudge  # noqa: E402
j = BenchJudge(s)
r = j.absolute(
    "What is the maximum message size in NimbusDB Pro tier?",
    "256 MB",
    "NimbusDB Pro tier: messages up to 256 MB; Starter caps at 16 MB.",
    "The maximum message size for the Pro tier is 256 MB.",
)
print("4. judge absolute: correctness=%s faithfulness=%s abstention=%s" % (
    r.get("correctness"), r.get("faithfulness"), r.get("abstention")))
ok = (r.get("correctness") or 0) >= 0.8 and (r.get("faithfulness") or 0) >= 0.9
print("   canary-style check:", "PASS" if ok else "FAIL")
print("DONE")
