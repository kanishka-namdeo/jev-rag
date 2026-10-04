#!/usr/bin/env python3
"""Render the Layer-2 arm chart straight from a merged testbench run.

This script takes its figures from analyze_testbench.analyze(), so the PNG can never
drift from the Markdown report generated in the same pass
(docs/parallel-bench-runbook.md §6). It is the only generated chart in the repo —
architecture and pipeline diagrams are Mermaid in the Markdown.

Usage (from backend/, merged DB as the data dir):
  JEVRAG_DATA_DIR=data_merged .venv/bin/python scripts/plot_testbench_arms.py RUN_ID \
      --out ../docs/assets/img/layer2-arm-results.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_testbench import analyze  # noqa: E402

BASE_COLOR = "#2563eb"
ARM_COLOR = "#0d9488"
NULL_COLOR = "#9ca3af"


def _pct(value):
    return "—" if value is None else f"{value * 100:.1f}%"


def plot(report: dict, out: Path) -> None:
    arms = report["arms"]
    base = report["base_arm"]
    order = sorted(arms, key=lambda a: (arms[a].get("correctness") or 0), reverse=True)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6.2), dpi=150)
    title = (f"Layer-2 testbench — {report['label']}\n"
             f"{report['run_id'][:8]} · {len(order)} arms · base arm '{base}' · "
             "judge: model-family-independent")
    fig.suptitle(title, fontsize=13, fontweight="bold", y=0.99)

    # ── panel 1: judge correctness with Wilson CI, paired delta vs base ──────────
    ys = range(len(order))
    corr = [arms[a].get("correctness") or 0.0 for a in order]
    errs = []
    for a in order:
        c = arms[a].get("correctness") or 0.0
        lo, hi = arms[a].get("correctness_ci95_wilson") or (c, c)
        errs.append([max(0.0, c - lo) * 100, max(0.0, hi - c) * 100])
    colors = [BASE_COLOR if a == base else ARM_COLOR for a in order]
    # reserve a right-hand gutter so the Δ/q annotations never sit on top of a whisker
    bar_extent = max(100.0, max(corr) * 100)
    xlim = bar_extent + 42
    ax1.barh(list(ys), [c * 100 for c in corr], color=colors, alpha=.85,
             xerr=[[e[0] for e in errs], [e[1] for e in errs]],
             error_kw=dict(ecolor="#334155", lw=1, capsize=3, alpha=.7), zorder=3)
    ax1.set_yticks(list(ys), [f"{a}  ({arms[a]['n']})" for a in order])
    ax1.invert_yaxis()
    ax1.set_xlabel("judge correctness (%)  ·  whiskers: 95% Wilson CI")
    ax1.set_xlim(0, xlim)
    ax1.grid(axis="x", ls=":", alpha=.5, zorder=0)
    ax1.set_xticks([t for t in (0, 20, 40, 60, 80, 100) if t <= bar_extent + 1])
    for i, a in enumerate(order):
        vs = arms[a].get("vs_base") or {}
        q = (report.get("bh_fdr") or {}).get(a)
        if a == base:
            tag = "reference"
        elif vs.get("n_paired"):
            sig = "✓" if (q is not None and q < 0.05) else "n.s."
            tag = f"Δ{vs['accuracy_delta'] * 100:+.1f}pp  q={q:.3f} {sig}" if q is not None \
                else f"Δ{vs['accuracy_delta'] * 100:+.1f}pp"
        else:
            tag = "unpaired"
        ax1.text(bar_extent + 2, i, tag,
                 va="center", fontsize=8, color="#0f172a")
    ax1.axvline((arms.get(base, {}).get("correctness") or 0) * 100, color=BASE_COLOR,
                ls="--", lw=1, alpha=.6, zorder=2)

    # ── panel 2: latency and escalation — the cost side of each arm ──────────────
    lat = [(arms[a].get("latency_ms") or {}).get("p50") or 0 for a in order]
    esc = [arms[a].get("escalation_rate") for a in order]
    ax2.barh(list(ys), [l / 1000 for l in lat], color="#f59e0b", alpha=.8, zorder=3)
    ax2.set_yticks(list(ys), [f"{a}  ({arms[a]['n']})" for a in order])
    ax2.invert_yaxis()
    ax2.set_xlabel("median latency p50 (s)")
    ax2.grid(axis="x", ls=":", alpha=.5, zorder=0)
    ax3 = ax2.twiny()
    ax3.set_ylim(ax2.get_ylim())
    ax3.scatter([e * 100 if e is not None else 0 for e in esc], list(ys),
                color="#7c3aed", s=34, zorder=4, label="escalation rate")
    ax3.set_xlabel("escalation rate (%)", color="#7c3aed")
    ax3.tick_params(axis="x", colors="#7c3aed")
    top = max([max(l / 1000 for l in lat), 1])
    ax2.set_xlim(0, top * 1.18)
    # headroom past 100% so an always-escalating arm's annotation is not clipped
    ax3.set_xlim(0, 132)
    ax3.set_xticks([0, 20, 40, 60, 80, 100])
    for i, a in enumerate(order):
        e = esc[i]
        ax3.text((e or 0) * 100 + 1.5, i, f"{(e or 0) * 100:.0f}% / ${arms[a]['cost_usd']:.3f}",
                 va="center", fontsize=8, color="#4c1d95")

    fig.text(0.01, 0.01,
             f"triples {sum(a['n'] for a in arms.values())} · "
             f"error rows {sum(a['errors'] for a in arms.values())} · "
             f"total cost ${sum(a['cost_usd'] for a in arms.values()):.3f} · "
             "paired: exact McNemar, bootstrap 50k seed 42, BH-FDR across the arm family",
             fontsize=8, color="#475569")
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    print(f"saved: {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--base", default="base")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2]
                                         / "docs" / "assets" / "img"
                                         / "layer2-arm-results.png"))
    args = ap.parse_args()
    report = analyze(args.run_id, base=args.base)
    plot(report, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
