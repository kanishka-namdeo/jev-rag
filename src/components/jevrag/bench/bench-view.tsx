"use client";

import { useEffect } from "react";
import { FlaskConical, Loader2, Play, Trash2, Zap } from "lucide-react";

import { useBench } from "@/lib/jevrag/bench-store";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { ResultsDashboard } from "./results-dashboard";

function fmtDuration(started: string, finished: string): string {
  if (!started || !finished) return "";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const min = Math.floor(ms / 60000);
  const sec = Math.round((ms % 60000) / 1000);
  return min > 0 ? `${min}m ${sec}s` : `${sec}s`;
}

export function BenchView() {
  const {
    scenarios, selected, toggleScenario, selectAllScenarios,
    runs, activeRunId, selectedRunId, selectRun, startRun, starting,
    runnerActive, init, loading, deleteRun, detail,
  } = useBench();

  useEffect(() => {
    void init();
  }, [init]);

  const activeRun = runs.find((r) => r.id === activeRunId);
  const selectedRun = runs.find((r) => r.id === selectedRunId);
  const busy = runnerActive || Boolean(activeRun);
  const pct = activeRun
    ? activeRun.progress.total > 0
      ? Math.round((activeRun.progress.done / activeRun.progress.total) * 100)
      : 0
    : 0;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-6xl space-y-5 px-4 py-5">
        {/* ── header ──────────────────────────────────────────── */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
              <FlaskConical className="h-5 w-5 text-emerald-600" />
              RAG Benchmark Lab
            </h1>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted-foreground">
              Traditional vs Hybrid (Jev System-One) pipelines over six document scenarios.
              Deterministic retrieval metrics + independent LLM judge (kimi-k2.5,
              position-swapped pairwise) — methodology in docs/benchmarking.md.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {detail?.run.summary?.judge && (
              <Badge variant="outline" className="gap-1 border-emerald-600/40 text-[10px] text-emerald-700 dark:text-emerald-400">
                <Zap className="h-3 w-3" />
                judge {detail.run.summary.judge.model} · self-test {detail.run.summary.judge.selftest_agreement ?? "n/a"}
              </Badge>
            )}
            {runs.length > 0 && (
              <Select value={selectedRunId ?? ""} onValueChange={(v) => void selectRun(v)}>
                <SelectTrigger className="h-8 w-56 text-xs">
                  <SelectValue placeholder="Select run…" />
                </SelectTrigger>
                <SelectContent>
                  {runs.map((r) => (
                    <SelectItem key={r.id} value={r.id} className="text-xs">
                      {r.status === "completed" ? "✓" : r.status === "running" ? "▶" : "·"}{" "}
                      {r.label.length > 34 ? `${r.label.slice(0, 34)}…` : r.label}
                      {r.status === "completed" && r.started_at && r.finished_at
                        ? ` (${fmtDuration(r.started_at, r.finished_at)})`
                        : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {selectedRunId && selectedRun?.status === "completed" && (
              <Button
                variant="ghost" size="sm" className="h-8 text-xs"
                onClick={() => void deleteRun(selectedRunId)}
                aria-label="Delete run"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>

        {/* ── active run progress ─────────────────────────────── */}
        {activeRun && (
          <Card className="border-emerald-600/30">
            <CardContent className="space-y-2 py-3">
              <div className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2 font-medium">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-emerald-600" />
                  {activeRun.status === "cancelling" ? "Cancelling…" : "Running benchmark"} · {activeRun.label}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {activeRun.progress.done}/{activeRun.progress.total} questions · {pct}%
                </span>
              </div>
              <Progress value={pct} className="h-1.5" />
              <p className="truncate font-mono text-[10px] text-muted-foreground">
                {activeRun.progress.stage}
              </p>
              {selectedRunId === activeRunId && detail && detail.results.length > 0 && (
                <p className="text-[10px] text-muted-foreground">
                  {detail.results.length} result rows streamed so far — dashboard updates live.
                </p>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── scenario selection ──────────────────────────────── */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Scenarios</h2>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" className="h-7 text-[11px]" onClick={selectAllScenarios}>
                Select all
              </Button>
              <Button
                size="sm"
                className="h-8 text-xs"
                disabled={busy || starting || selected.length === 0}
                onClick={() => void startRun()}
              >
                {starting || busy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1 h-3.5 w-3.5" />}
                Run benchmark{selected.length > 0 ? ` (${selected.length})` : ""}
              </Button>
            </div>
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {scenarios.map((s) => {
              const checked = selected.includes(s.id);
              return (
                <label
                  key={s.id}
                  className={`group cursor-pointer rounded-lg border p-3 transition-colors ${
                    checked ? "border-emerald-600/50 bg-emerald-500/5" : "bg-card hover:bg-accent"
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => toggleScenario(s.id)}
                      className="mt-0.5"
                      aria-label={`Include ${s.name}`}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-medium leading-tight">{s.name}</p>
                      <p className="mt-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                        {s.category}
                      </p>
                      <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
                        {s.description}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-1">
                        <Badge variant="secondary" className="px-1.5 text-[9px]">
                          {s.doc_count} docs
                        </Badge>
                        <Badge variant="secondary" className="px-1.5 text-[9px]">
                          {s.question_count} Q
                        </Badge>
                        {s.unanswerable > 0 && (
                          <Badge variant="secondary" className="px-1.5 text-[9px] text-amber-600 dark:text-amber-400">
                            {s.unanswerable} unanswerable
                          </Badge>
                        )}
                      </div>
                    </div>
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        {/* ── results ─────────────────────────────────────────── */}
        {loading && (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> loading runs…
          </div>
        )}
        {!loading && selectedRunId && <ResultsDashboard />}
        {!loading && !selectedRunId && runs.length === 0 && (
          <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
            No benchmark runs yet — select scenarios above and press{" "}
            <span className="font-medium text-foreground">Run benchmark</span>.
          </div>
        )}
      </div>
    </div>
  );
}
