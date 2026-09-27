"""Export a completed benchmark run to a markdown snapshot + JSON artifact.

Usage:
    cd backend && .venv/bin/python scripts/export_bench_results.py <run_id> [out.md]

Writes docs/benchmark-results.md (repo copy) and backend/data/bench_exports/<run_id>.json
(full machine-readable results) by default.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db import BenchResult, BenchRun, db_session  # noqa: E402
from app.bench.scenarios import SCENARIO_MAP  # noqa: E402


def pct(v, d=1):
    return "—" if v is None else f"{v * 100:.{d}f}%"


def num(v, d=3):
    return "—" if v is None else f"{v:.{d}f}"


def ms(v):
    return "—" if v is None else (f"{v / 1000:.1f}s" if v >= 1000 else f"{v:.0f}ms")


def arm_line(a: dict) -> str:
    r = a.get("retrieval", {})
    lat = a.get("latency_ms", {})
    return (f"correctness **{pct(a.get('correctness'))}** · faithfulness "
            f"**{pct(a.get('faithfulness'))}** · hit@4 **{pct(r.get('hit4'), 0)}** · "
            f"MRR **{num(r.get('mrr'))}** · nDCG@10 **{num(r.get('ndcg10'))}** · "
            f"p50 {ms(lat.get('p50'))} · cost ${a.get('cost_usd', 0) / max(a.get('n', 1), 1):.4f}/q")


def main(run_id: str, out_md: str = "") -> None:
    with db_session() as session:
        run = session.get(BenchRun, run_id)
        if run is None:
            raise SystemExit(f"run {run_id} not found")
        rows = session.execute(
            select(BenchResult).where(BenchResult.run_id == run_id)
            .order_by(BenchResult.scenario_id, BenchResult.question_id, BenchResult.mode)
        ).scalars().all()

    summary = run.summary or {}
    if not summary:
        raise SystemExit(f"run {run_id} has no summary (status={run.status})")

    # ---------------- machine-readable artifact
    export_dir = BACKEND / "data" / "bench_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / f"{run_id}.json").write_text(json.dumps({
        "run": {
            "id": run.id, "label": run.label, "status": run.status,
            "scenario_ids": run.scenario_ids, "judge_model": run.judge_model,
            "config": run.config, "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "judge_selftest": run.judge_selftest,
        },
        "summary": summary,
        "results": [
            {c.name: getattr(r, c.name) for c in r.__table__.columns} for r in rows
        ],
    }, ensure_ascii=False, indent=1, default=str))

    # ---------------- markdown snapshot
    ov = summary.get("overall", {})
    t, h = ov.get("traditional", {}), ov.get("hybrid", {})
    pw = ov.get("pairwise", {}) or {}
    gate = summary.get("gate_analysis", {}) or {}
    ab = summary.get("abstention_analysis", {})
    judge = summary.get("judge", {})

    def abget(k, f):
        return (ab.get(k) or {}).get(f)

    L: list[str] = []
    L.append("# Benchmark Results — Traditional vs Hybrid (Jev) RAG")
    L.append("")
    L.append(f"- **Run**: `{run.id}` — {run.label}")
    L.append(f"- **Status**: {run.status} · {len(rows)} result rows · {ov.get('questions', '?')} questions × 2 systems")
    if run.started_at and run.finished_at:
        dur = (run.finished_at - run.started_at).total_seconds()
        L.append(f"- **Duration**: {dur / 60:.1f} min")
    L.append(f"- **Judge**: {judge.get('model', run.judge_model)} (independent family; self-test agreement "
             f"**{pct(judge.get('selftest_agreement'), 0)}**)")
    cfg = run.config or {}
    L.append(f"- **Config**: top_k retrieve/use = {cfg.get('top_k_retrieve')}/{cfg.get('top_k_use')} · "
             f"generators {cfg.get('llm_default')} / {cfg.get('llm_reasoning')} (hybrid routing) · "
             f"sufficiency threshold {cfg.get('sufficiency_threshold')}")
    L.append("")
    L.append("## Headline (all scenarios pooled)")
    L.append("")
    L.append("| metric | traditional | hybrid (Jev) |")
    L.append("|---|---|---|")
    L.append(f"| correctness (judge) | {pct(t.get('correctness'))} | {pct(h.get('correctness'))} |")
    L.append(f"| faithfulness (judge) | {pct(t.get('faithfulness'))} | {pct(h.get('faithfulness'))} |")
    rt, rh = t.get("retrieval", {}), h.get("retrieval", {})
    L.append(f"| hit@4 | {pct(rt.get('hit4'), 0)} | {pct(rh.get('hit4'), 0)} |")
    L.append(f"| MRR@10 | {num(rt.get('mrr'))} | {num(rh.get('mrr'))} |")
    L.append(f"| nDCG@10 | {num(rt.get('ndcg10'))} | {num(rh.get('ndcg10'))} |")
    L.append(f"| recall@4 | {pct(rt.get('recall4'), 0)} | {pct(rh.get('recall4'), 0)} |")
    lt, lh = t.get("latency_ms", {}), h.get("latency_ms", {})
    L.append(f"| latency p50 | {ms(lt.get('p50'))} | {ms(lh.get('p50'))} |")
    L.append(f"| latency p95 | {ms(lt.get('p95'))} | {ms(lh.get('p95'))} |")
    nt, nh = t.get("n", 1) or 1, h.get("n", 1) or 1
    L.append(f"| cost / query | ${t.get('cost_usd', 0) / nt:.4f} | ${h.get('cost_usd', 0) / nh:.4f} |")
    if pw:
        L.append(f"| pairwise win rate | — | {pct(pw.get('hybrid_win_rate'))} "
                 f"(W{pw.get('hybrid_wins')}/T{pw.get('ties')}/L{pw.get('traditional_wins')}, "
                 f"pos-consistency {pct(pw.get('position_consistency'), 0)}) |")
    L.append("")
    L.append("## Hybrid-only intelligence")
    L.append("")
    L.append("| metric | value |")
    L.append("|---|---|")
    lift = h.get("rerank_lift", {}) or {}
    L.append(f"| Jev rerank lift — hit@4 | {'+' if (lift.get('hit4') or 0) >= 0 else ''}{pct(lift.get('hit4'), 1)} |")
    L.append(f"| Jev rerank lift — MRR@10 | {'+' if (lift.get('mrr') or 0) >= 0 else ''}{num(lift.get('mrr'))} |")
    L.append(f"| Jev rerank lift — nDCG@10 | {'+' if (lift.get('ndcg10') or 0) >= 0 else ''}{num(lift.get('ndcg10'))} |")
    L.append(f"| sufficiency gate accuracy | {pct(gate.get('accuracy'), 1)} (Brier {num(gate.get('brier'))}, n={gate.get('n')}) |")
    L.append(f"| mean P(sufficient) | {num(h.get('sufficiency_mean'))} |")
    L.append(f"| mean verification (groundedness) | {num(h.get('verification_mean'))} |")
    L.append("")
    L.append("## Abstention & hallucination (out-of-scope scenario)")
    L.append("")
    L.append("| metric | traditional | hybrid |")
    L.append("|---|---|---|")
    L.append(f"| proper abstention (unanswerable) | {pct(abget('unanswerable_traditional', 'proper_abstention_rate'), 0)} | {pct(abget('unanswerable_hybrid', 'proper_abstention_rate'), 0)} |")
    L.append(f"| fabrication rate (unanswerable) | {pct(abget('unanswerable_traditional', 'fabrication_rate'), 0)} | {pct(abget('unanswerable_hybrid', 'fabrication_rate'), 0)} |")
    L.append(f"| over-abstention (answerable) | {pct(abget('answerable_traditional', 'over_abstention_rate'), 0)} | {pct(abget('answerable_hybrid', 'over_abstention_rate'), 0)} |")
    L.append("")
    L.append("## Per-scenario results")
    L.append("")
    for sid, s in (summary.get("scenarios", {}) or {}).items():
        name = SCENARIO_MAP[sid].name if sid in SCENARIO_MAP else sid
        L.append(f"### {name} (`{sid}`) — {s.get('questions', '?')} questions")
        L.append("")
        L.append(f"- **traditional**: {arm_line(s.get('traditional', {}))}")
        L.append(f"- **hybrid**: {arm_line(s.get('hybrid', {}))}")
        spw = s.get("pairwise", {}) or {}
        if spw:
            L.append(f"- **pairwise**: hybrid win rate {pct(spw.get('hybrid_win_rate'))} "
                     f"(W{spw.get('hybrid_wins')}/T{spw.get('ties')}/L{spw.get('traditional_wins')})")
        L.append("")
    L.append("## Per-question detail")
    L.append("")
    L.append("| scenario | q | system | correctness | faithfulness | verdict | hit@4 | model | latency |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        g = r.generation or {}
        ret = r.retrieval or {}
        tim = r.timings or {}
        verdict = g.get("abstention", "—")
        if r.error:
            verdict = f"error"
            corr = faith = "—"
        else:
            corr = num(g.get("correctness"), 2) if g.get("correctness") is not None else "—"
            faith = num(g.get("faithfulness"), 2) if g.get("faithfulness") is not None else "—"
        L.append(f"| {r.scenario_id} | {r.question_id} | {r.mode} | {corr} | {faith} | {verdict} | "
                 f"{ret.get('hit4', '—')} | {r.model or '—'} | {ms(tim.get('latency_ms'))} |")
    L.append("")
    L.append(f"_Methodology: docs/benchmarking.md · machine-readable artifact: "
             f"backend/data/bench_exports/{run_id}.json · generated {summary.get('generated_at', '')}._")

    dest = Path(out_md) if out_md else (BACKEND.parent / "docs" / "benchmark-results.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {dest} ({len(L)} lines) + {export_dir / f'{run_id}.json'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: export_bench_results.py <run_id> [out.md]")
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
