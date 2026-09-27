"use client";

import { useMemo } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Minus,
  Scale,
  ShieldCheck,
  Target,
  Timer,
} from "lucide-react";

import type { ArmMetrics, BenchResultRow, BenchSummary, ScenarioMeta } from "@/lib/jevrag/bench-api";
import { useBench } from "@/lib/jevrag/bench-store";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";

import { ResultsTable } from "./results-table";

/* ------------------------------------------------------------------ helpers */
const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
const num = (v: number | null | undefined, digits = 2) =>
  v == null ? "—" : v.toFixed(digits);
const ms = (v: number | null | undefined) =>
  v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v < 0.01 ? v.toFixed(4) : v.toFixed(3)}`);

/** Aggregate result rows client-side so the dashboard is alive during a run
 *  (the backend writes the canonical summary at completion). */
function liveSummary(results: BenchResultRow[], scenarios: ScenarioMeta[]): BenchSummary {
  const names = Object.fromEntries(scenarios.map((s) => [s.id, s.name]));
  const byScenario = new Map<string, BenchResultRow[]>();
  for (const r of results) {
    if (!byScenario.has(r.scenario_id)) byScenario.set(r.scenario_id, []);
    byScenario.get(r.scenario_id)!.push(r);
  }
  const arm = (rows: BenchResultRow[], mode: string): ArmMetrics => {
    const rs = rows.filter((r) => r.mode === mode);
    const mean = (xs: (number | null | undefined)[]) => {
      const vs = xs.filter((x): x is number => x != null);
      return vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null;
    };
    const lat = rs.map((r) => r.timings?.latency_ms ?? 0);
    const sorted = [...lat].sort((a, b) => a - b);
    const abst: Record<string, number> = {};
    for (const r of rs) {
      const k = r.generation?.abstention ?? "pending";
      abst[k] = (abst[k] ?? 0) + 1;
    }
    const retr = rs.filter((r) => Object.keys(r.retrieval ?? {}).length > 0);
    const hyb = mode === "hybrid";
    const naive = rs.filter((r) => Object.keys(r.naive_retrieval ?? {}).length > 0);
    const rm = (key: string) => mean(retr.map((r) => r.retrieval?.[key]));
    const nm = (key: string) => mean(naive.map((r) => r.naive_retrieval?.[key]));
    const out: ArmMetrics = {
      n: rs.length,
      correctness: mean(rs.map((r) => r.generation?.correctness)),
      faithfulness: mean(rs.map((r) => r.generation?.faithfulness)),
      abstention: abst,
      retrieval: retr.length
        ? Object.fromEntries(["hit1", "hit4", "hit10", "mrr", "recall4", "recall10", "ndcg10"]
            .map((k) => [k, rm(k)])
            .filter(([, v]) => v != null))
        : {},
      latency_ms: {
        mean: mean(lat),
        p50: sorted.length ? sorted[Math.floor(sorted.length / 2)] : null,
        p95: sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)] : null,
      },
      tokens_in: rs.reduce((a, r) => a + (r.tokens_in ?? 0), 0),
      tokens_out: rs.reduce((a, r) => a + (r.tokens_out ?? 0), 0),
      cost_usd: rs.reduce((a, r) => a + (r.cost_usd ?? 0), 0),
      errors: rs.filter((r) => r.error).length,
    };
    if (hyb) {
      out.sufficiency_mean = mean(rs.map((r) => r.sufficiency_p));
      out.verification_mean = mean(rs.map((r) => r.verification_p));
      if (naive.length && retr.length) {
        out.rerank_lift = Object.fromEntries(
          Object.keys(out.retrieval)
            .map((k) => [k, (rm(k) ?? 0) - (nm(k) ?? 0)])
            .filter(([, v]) => Number.isFinite(v)),
        );
      }
    }
    return out;
  };
  const pairwiseOf = (rows: BenchResultRow[]) => {
    const pw = rows.filter((r) => r.mode === "hybrid" && r.pairwise);
    if (!pw.length) return {};
    const wins = pw.filter((r) => r.pairwise!.winner === "hybrid").length;
    const losses = pw.filter((r) => r.pairwise!.winner === "traditional").length;
    const ties = pw.filter((r) => r.pairwise!.winner === "tie").length;
    return {
      n: pw.length, hybrid_wins: wins, traditional_wins: losses, ties,
      hybrid_win_rate: (wins + 0.5 * ties) / pw.length,
      position_consistency: pw.filter((r) => r.pairwise!.position_consistent).length / pw.length,
    };
  };
  const scenariosOut: BenchSummary["scenarios"] = {};
  for (const [sid, rows] of byScenario) {
    scenariosOut[sid] = {
      name: names[sid] ?? sid,
      questions: new Set(rows.map((r) => r.question_id)).size,
      traditional: arm(rows, "traditional"),
      hybrid: arm(rows, "hybrid"),
      pairwise: pairwiseOf(rows),
    };
  }
  const gateRows = results.filter((r) => r.mode === "hybrid" && r.sufficiency_p != null);
  const gateCorrect = gateRows.filter((r) => (r.sufficiency_p! >= 0.5) === r.answerable).length;
  const abstention: BenchSummary["abstention_analysis"] = {};
  for (const ansFlag of [true, false]) {
    for (const mode of ["traditional", "hybrid"] as const) {
      const grp = results.filter((r) => r.answerable === ansFlag && r.mode === mode);
      const cnt = (k: string) => grp.filter((r) => r.generation?.abstention === k).length;
      const n = grp.length || 1;
      abstention[`${ansFlag ? "answerable" : "unanswerable"}_${mode}`] = {
        n: grp.length,
        answered: cnt("answered"), abstained: cnt("abstained"), fabricated: cnt("fabricated"),
        proper_abstention_rate: ansFlag ? null : cnt("abstained") / n,
        over_abstention_rate: ansFlag ? cnt("abstained") / n : null,
        fabrication_rate: ansFlag ? null : cnt("fabricated") / n,
      } as never;
    }
  }
  return {
    scenarios: scenariosOut,
    overall: {
      questions: new Set(results.map((r) => `${r.scenario_id}/${r.question_id}`)).size,
      traditional: arm(results, "traditional"),
      hybrid: arm(results, "hybrid"),
      pairwise: pairwiseOf(results),
    },
    abstention_analysis: abstention,
    gate_analysis: gateRows.length
      ? { n: gateRows.length, accuracy: gateCorrect / gateRows.length,
          brier: gateRows.reduce((a, r) => a + (r.sufficiency_p! - (r.answerable ? 1 : 0)) ** 2, 0) / gateRows.length }
      : {},
    judge: { model: "(live)", selftest_agreement: null },
    generated_at: new Date().toISOString(),
  };
}

/* ------------------------------------------------------------------ cards */
function Delta({ trad, hyb, better }: { trad: number | null; hyb: number | null; better: "higher" | "lower" }) {
  if (trad == null || hyb == null) return null;
  const diff = hyb - trad;
  const good = better === "higher" ? diff > 0.0005 : diff < -0.0005;
  const bad = better === "higher" ? diff < -0.0005 : diff > 0.0005;
  if (!good && !bad) return <Minus className="h-3 w-3 text-muted-foreground" />;
  const Icon = good ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] font-medium tabular-nums ${good ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
      <Icon className="h-3 w-3" />
      {Math.abs(diff) < 1 ? (Math.abs(diff) * 100).toFixed(1) + "pp" : Math.abs(diff).toFixed(1)}
    </span>
  );
}

function MetricCard({ title, icon, trad, hyb, fmt, delta, hint }: {
  title: string; icon: React.ReactNode;
  trad: number | null; hyb: number | null;
  fmt: (v: number | null) => string;
  delta?: { better: "higher" | "lower" }; hint?: string;
}) {
  return (
    <Card className="gap-2 py-3">
      <CardHeader className="px-3 pb-0">
        <CardTitle className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
          {icon} {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 px-3">
        <div className="text-right">
          <p className="font-mono text-sm font-semibold tabular-nums text-sky-600 dark:text-sky-400">{fmt(trad)}</p>
          <p className="text-[9px] text-muted-foreground">traditional</p>
        </div>
        {delta ? (
          <div className="flex justify-center">
            <Delta trad={trad} hyb={hyb} better={delta.better} />
          </div>
        ) : (
          <div className="h-1 w-1 rounded-full bg-border" />
        )}
        <div>
          <p className="font-mono text-sm font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">{fmt(hyb)}</p>
          <p className="text-[9px] text-muted-foreground">hybrid</p>
        </div>
      </CardContent>
      {hint && <p className="px-3 text-[9px] text-muted-foreground">{hint}</p>}
    </Card>
  );
}

/* ------------------------------------------------------------------ charts */
const CHART_CFG = {
  trad: { label: "Traditional", color: "var(--chart-trad, #0ea5e9)" },
  hyb: { label: "Hybrid", color: "var(--chart-hyb, #10b981)" },
} as const;

function ScenarioChart({ title, field, data, domain }: {
  title: string; field: string; data: { scenario: string; trad: number | null; hyb: number | null }[];
  domain: [number, number];
}) {
  return (
    <Card className="gap-2 py-3">
      <CardHeader className="px-3 pb-0">
        <CardTitle className="text-[11px] font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent className="px-2">
        <ChartContainer config={CHART_CFG} className="h-[168px] w-full">
          <BarChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" strokeOpacity={0.25} />
            <XAxis dataKey="scenario" tickLine={false} axisLine={false} fontSize={9} interval={0} tickMargin={4} />
            <ChartTooltip content={<ChartTooltipContent />} cursor={{ fillOpacity: 0.1 }} />
            <Bar dataKey="trad" fill="#0ea5e9" radius={[3, 3, 0, 0]} maxBarSize={26} domain={domain} />
            <Bar dataKey="hyb" fill="#10b981" radius={[3, 3, 0, 0]} maxBarSize={26} domain={domain} />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ main */
export function ResultsDashboard() {
  const detail = useBench((s) => s.detail);
  const scenarios = useBench((s) => s.scenarios);
  const run = detail?.run;
  const results = detail?.results ?? [];
  const live = useMemo(
    () => (run?.summary ? null : results.length >= 2 ? liveSummary(results, scenarios) : null),
    [run?.summary, results, scenarios],
  );
  const summary = run?.summary ?? live;

  if (!run) return null;
  if (!summary) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        {run.status === "running" || run.status === "queued"
          ? `Run in progress — ${results.length} result rows collected; the dashboard appears once answers start landing.`
          : run.error
            ? `Run failed: ${run.error}`
            : "No results yet for this run."}
      </div>
    );
  }

  const order = scenarios.map((s) => s.id).filter((id) => id in summary.scenarios);
  const label = (id: string) => (scenarios.find((s) => s.id === id)?.name ?? id).split(" ")[0];
  const chart = (field: string) =>
    order.map((id) => ({
      scenario: label(id),
      trad: summary.scenarios[id].traditional[field] ?? null,
      hyb: summary.scenarios[id].hybrid[field] ?? null,
    }));

  const t = summary.overall.traditional;
  const h = summary.overall.hybrid;
  const pw = summary.overall.pairwise;
  const gate = summary.gate_analysis as { n?: number; accuracy?: number; brier?: number };
  const ab = summary.abstention_analysis;
  const getAb = (k: string) =>
    (ab[k] ?? {}) as { n?: number; answered?: number | null; abstained?: number | null; fabricated?: number | null; proper_abstention_rate?: number | null; over_abstention_rate?: number | null; fabrication_rate?: number | null };
  const ooT = getAb("unanswerable_traditional");
  const ooH = getAb("unanswerable_hybrid");
  const anT = getAb("answerable_traditional");
  const anH = getAb("answerable_hybrid");
  const liftHit = h.rerank_lift?.hit4;
  const liftMrr = h.rerank_lift?.mrr;

  return (
    <div className="space-y-4">
      {live && (
        <p className="text-[10px] text-muted-foreground">
          live view — {results.length} rows so far, aggregated client-side while the run is in progress
        </p>
      )}

      {/* overall metric cards */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard title="Correctness (judge)" icon={<Target className="h-3.5 w-3.5" />} trad={t.correctness} hyb={h.correctness} fmt={(v) => pct(v, 1)} delta={{ better: "higher" }} />
        <MetricCard title="Faithfulness (judge)" icon={<ShieldCheck className="h-3.5 w-3.5" />} trad={t.faithfulness} hyb={h.faithfulness} fmt={(v) => pct(v, 1)} delta={{ better: "higher" }} />
        <MetricCard title="Hit@4" icon={<Target className="h-3.5 w-3.5" />} trad={t.retrieval.hit4 ?? null} hyb={h.retrieval.hit4 ?? null} fmt={(v) => pct(v)} delta={{ better: "higher" }} />
        <MetricCard title="MRR@10" icon={<Target className="h-3.5 w-3.5" />} trad={t.retrieval.mrr ?? null} hyb={h.retrieval.mrr ?? null} fmt={(v) => num(v, 3)} delta={{ better: "higher" }} />
        <MetricCard title="Latency p50" icon={<Timer className="h-3.5 w-3.5" />} trad={t.latency_ms.p50} hyb={h.latency_ms.p50} fmt={ms} delta={{ better: "lower" }} hint="pipeline only (judge excluded)" />
        <MetricCard title="Cost / query" icon={<Scale className="h-3.5 w-3.5" />} trad={t.n ? t.cost_usd / t.n : null} hyb={h.n ? h.cost_usd / h.n : null} fmt={usd} delta={{ better: "lower" }} hint="cloud LLM generation" />
      </div>

      {/* pairwise + gate + abstention row */}
      <div className="grid gap-2.5 lg:grid-cols-3">
        <Card className="gap-2 py-3">
          <CardHeader className="px-3 pb-0">
            <CardTitle className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
              <Scale className="h-3.5 w-3.5" /> Pairwise judge (both orders, position-swapped)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 px-3 text-xs">
            {pw && "n" in pw && pw.n ? (
              <>
                <div className="flex items-baseline justify-between">
                  <span className="text-muted-foreground">Hybrid win rate</span>
                  <span className="font-mono text-sm font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                    {pct(pw.hybrid_win_rate, 1)}
                  </span>
                </div>
                <div className="flex justify-between text-[10px] text-muted-foreground">
                  <span>hybrid {pw.hybrid_wins} · tie {pw.ties} · trad {pw.traditional_wins}</span>
                  <span>pos-consistency {pct(pw.position_consistency)}</span>
                </div>
              </>
            ) : (
              <p className="text-[10px] text-muted-foreground">no pairwise verdicts yet</p>
            )}
          </CardContent>
        </Card>

        <Card className="gap-2 py-3">
          <CardHeader className="px-3 pb-0">
            <CardTitle className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
              <Target className="h-3.5 w-3.5" /> Jev sufficiency gate (hybrid)
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-x-3 gap-y-1 px-3 text-xs">
            <span className="text-muted-foreground">accuracy</span>
            <span className="text-right font-mono tabular-nums">{gate?.accuracy != null ? pct(gate.accuracy, 1) : "—"}</span>
            <span className="text-muted-foreground">Brier score</span>
            <span className="text-right font-mono tabular-nums">{gate?.brier != null ? num(gate.brier, 3) : "—"}</span>
            <span className="text-muted-foreground">mean P(sufficient)</span>
            <span className="text-right font-mono tabular-nums">{num(h.sufficiency_mean, 3)}</span>
            <span className="text-muted-foreground">mean verification</span>
            <span className="text-right font-mono tabular-nums">{num(h.verification_mean, 3)}</span>
          </CardContent>
        </Card>

        <Card className="gap-2 py-3">
          <CardHeader className="px-3 pb-0">
            <CardTitle className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
              <ShieldCheck className="h-3.5 w-3.5" /> Jev rerank lift (hybrid)
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-x-3 gap-y-1 px-3 text-xs">
            <span className="text-muted-foreground">hit@4 lift</span>
            <span className={`text-right font-mono tabular-nums ${liftHit == null ? "" : liftHit >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
              {liftHit == null ? "—" : `${liftHit >= 0 ? "+" : ""}${(liftHit * 100).toFixed(1)}pp`}
            </span>
            <span className="text-muted-foreground">MRR lift</span>
            <span className={`text-right font-mono tabular-nums ${liftMrr == null ? "" : liftMrr >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
              {liftMrr == null ? "—" : `${liftMrr >= 0 ? "+" : ""}${liftMrr.toFixed(3)}`}
            </span>
            <span className="col-span-2 mt-0.5 text-[9px] leading-snug text-muted-foreground">
              post-Jev-rerank top-4 vs naive embedding top-4 (what traditional retrieves).
            </span>
          </CardContent>
        </Card>
      </div>

      {/* abstention analysis */}
      <Card className="gap-2 py-3">
        <CardHeader className="px-3 pb-0">
          <CardTitle className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5" /> Abstention &amp; hallucination (out-of-scope scenario)
          </CardTitle>
        </CardHeader>
        <CardContent className="px-3">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-[10px] text-muted-foreground">
                <th className="py-1.5 text-left font-medium">metric</th>
                <th className="py-1.5 text-right font-medium text-sky-600 dark:text-sky-400">traditional</th>
                <th className="py-1.5 text-right font-medium text-emerald-600 dark:text-emerald-400">hybrid</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              <tr className="border-b border-border/50">
                <td className="py-1.5 font-sans text-muted-foreground">proper abstention (unanswerable Q)</td>
                <td className="text-right">{pct(ooT.proper_abstention_rate as number | null, 0)}</td>
                <td className="text-right">{pct(ooH.proper_abstention_rate as number | null, 0)}</td>
              </tr>
              <tr className="border-b border-border/50">
                <td className="py-1.5 font-sans text-muted-foreground">fabrication rate (unanswerable Q)</td>
                <td className="text-right">{pct(ooT.fabrication_rate as number | null, 0)}</td>
                <td className="text-right">{pct(ooH.fabrication_rate as number | null, 0)}</td>
              </tr>
              <tr>
                <td className="py-1.5 font-sans text-muted-foreground">over-abstention (answerable Q)</td>
                <td className="text-right">{pct(anT.over_abstention_rate as number | null, 0)}</td>
                <td className="text-right">{pct(anH.over_abstention_rate as number | null, 0)}</td>
              </tr>
            </tbody>
          </table>
          <p className="mt-2 text-[9px] text-muted-foreground">
            counts — unanswerable: trad {ooT.abstained ?? 0} abstained / {ooT.fabricated ?? 0} fabricated / {ooT.answered ?? 0} answered (n={ooT.n ?? 0});
            hybrid {ooH.abstained ?? 0}/{ooH.fabricated ?? 0}/{ooH.answered ?? 0} (n={ooH.n ?? 0}).
          </p>
        </CardContent>
      </Card>

      {/* charts */}
      <div className="grid gap-2.5 md:grid-cols-2">
        <ScenarioChart title="Correctness per scenario (judge, 0–1)" field="correctness" data={chart("correctness")} domain={[0, 1]} />
        <ScenarioChart title="Faithfulness per scenario (judge, 0–1)" field="faithfulness" data={chart("faithfulness")} domain={[0, 1]} />
        <ScenarioChart title="Hit@4 per scenario" field="hit4" data={chart("hit4")} domain={[0, 1]} />
        <ScenarioChart title="MRR@10 per scenario" field="mrr" data={chart("mrr")} domain={[0, 1]} />
      </div>

      {/* per-question table */}
      <ResultsTable />
    </div>
  );
}
