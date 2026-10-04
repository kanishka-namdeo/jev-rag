# Docs

Start here. Pick the lane that matches what you're trying to do.

## Use it

Install, then day-to-day.

1. [setup.md](setup.md) — fresh-machine install and verification (Windows: [windows-setup.md](windows-setup.md))
2. [usage.md](usage.md) — upload, ask, read citations, run the Benchmark Lab
3. [configuration.md](configuration.md) — every setting, its real default, and what it costs
4. [troubleshooting.md](troubleshooting.md) — stuck? start here, in symptom order

## Understand it

How it works, and why it works that way.

- [glossary.md](glossary.md) — the vocabulary (System One/Two, escalation gate, RRF, McNemar)
- [architecture.md](architecture.md) — components, data flow, deployment topology
- [hybrid-design.md](hybrid-design.md) — the decision pipeline and its configuration knobs
- [rag-upgrade-2026.md](rag-upgrade-2026.md) — why v3 gates on retrieval scores (research synthesis)
- [jev-improvements-research.md](jev-improvements-research.md) — decision patterns beyond model routing
- [api.md](api.md) — REST + SSE wire protocol
- [setup-gpu.md](setup-gpu.md) — CUDA on Linux and the WSL2 CPU fallback

## Measure it

Numbers, how they were produced, and how to reproduce them.

- [results.md](results.md) — the entry point: headline numbers, key findings, v1→v2→v3
- [benchmarking.md](benchmarking.md) — metric definitions, judge fairness protocol, statistics
- [testbench-design.md](testbench-design.md) — the pre-declared hypotheses and arms
- [testbench-results-layer1.md](testbench-results-layer1.md) — retrieval ablations
- [testbench-results-layer2-full9-r2.md](testbench-results-layer2-full9-r2.md) — the current 9-arm record (run 4ec32592, 882 triples), plus why its pooled correctness cannot be compared with the earlier draw
- [testbench-results-layer2-full9.md](testbench-results-layer2-full9.md) — the superseded 9-arm draw (run 36abefc6), kept as the reproducibility contrast
- [testbench-results-hgate.md](testbench-results-hgate.md) — the earlier 4-arm draw (reproducibility contrast)
- [benchmark-results.md](benchmark-results.md) — complete run history
- [benchmark-public.md](benchmark-public.md) — public wave 1 (run 4dc6c46e): SQuAD + HotpotQA, hybrid vs traditional, 50 questions
- [benchmark-public-wave2.md](benchmark-public-wave2.md) — public wave 2 (run bcfdd120): TriviaQA + 2WikiMultiHopQA + MuSiQue, completing the five-benchmark 98-question set
- [benchmark-v2-ablation.md](benchmark-v2-ablation.md) — the v2 regression attributed to the passage battery: battery off recovers v1-level hybrid numbers in 4/6 scenarios (exactly or better), the other two recovering most of the gap (run bf05f585)
- [rag-upgrade-2026-results.md](rag-upgrade-2026-results.md) — the v3 headline run (16814bd5): upgraded traditional vs hybrid on 98 public questions, plus the H-GATE ablation
- [parallel-bench-runbook.md](parallel-bench-runbook.md) — multi-worker runs on a workstation

## Contribute

[CONTRIBUTING.md](../CONTRIBUTING.md) · [SECURITY.md](../SECURITY.md) · [CHANGELOG.md](../CHANGELOG.md) · [AGENTS.md](../AGENTS.md) (agent/dev contracts) · [dev/](dev/) (raw worklog and dated snapshots) · [superpowers/](superpowers/) (dated plan and spec artifacts for the docs work itself)
