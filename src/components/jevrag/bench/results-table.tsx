"use client";

import { Fragment, useState } from "react";
import { ChevronRight, Loader2 } from "lucide-react";

import { useBench, useFilteredResults } from "@/lib/jevrag/bench-store";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const ABST_STYLE: Record<string, string> = {
  answered: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
  abstained: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  fabricated: "bg-red-500/10 text-red-700 dark:text-red-400",
  error: "bg-muted text-muted-foreground",
};

function shortFile(f: string): string {
  return f.replace(/^bench-[a-z]+-\d+-/, "").replace(/\.md$/, "");
}

export function ResultsTable() {
  const rows = useFilteredResults();
  const { scenarios, filterMode, setFilterMode, filterScenario, setFilterScenario, detail } = useBench();
  const [open, setOpen] = useState<string | null>(null);
  const runStatus = detail?.run.status;

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-6 text-center text-xs text-muted-foreground">
        No result rows match the current filters.
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">
          Per-question results
          <span className="ml-2 text-[10px] font-normal text-muted-foreground">
            {rows.length} rows
          </span>
        </h2>
        <div className="flex items-center gap-2">
          <Select value={filterMode} onValueChange={(v) => setFilterMode(v as typeof filterMode)}>
            <SelectTrigger className="h-7 w-32 text-[11px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">both systems</SelectItem>
              <SelectItem value="traditional" className="text-xs">traditional</SelectItem>
              <SelectItem value="hybrid" className="text-xs">hybrid</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filterScenario || "all"} onValueChange={(v) => setFilterScenario(v === "all" ? "" : v)}>
            <SelectTrigger className="h-7 w-44 text-[11px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">all scenarios</SelectItem>
              {scenarios.map((s) => (
                <SelectItem key={s.id} value={s.id} className="text-xs">{s.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead className="w-6 px-2 py-1.5" />
              <TableHead className="px-2 py-1.5 text-[10px] font-medium">scenario</TableHead>
              <TableHead className="px-2 py-1.5 text-[10px] font-medium">question</TableHead>
              <TableHead className="px-2 py-1.5 text-[10px] font-medium">system</TableHead>
              <TableHead className="px-2 py-1.5 text-right text-[10px] font-medium">correct</TableHead>
              <TableHead className="px-2 py-1.5 text-right text-[10px] font-medium">faithful</TableHead>
              <TableHead className="px-2 py-1.5 text-center text-[10px] font-medium">verdict</TableHead>
              <TableHead className="px-2 py-1.5 text-right text-[10px] font-medium">hit@4</TableHead>
              <TableHead className="px-2 py-1.5 text-right text-[10px] font-medium">latency</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const isOpen = open === r.id;
              const lat = r.timings?.latency_ms;
              return (
                <Fragment key={r.id}>
                  <TableRow
                    className="cursor-pointer text-xs hover:bg-accent/50"
                    onClick={() => setOpen(isOpen ? null : r.id)}
                  >
                    <TableCell className="px-2 py-1.5">
                      <ChevronRight
                        className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${isOpen ? "rotate-90" : ""}`}
                      />
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-muted-foreground">
                      {shortScenario(r.scenario_id)}
                    </TableCell>
                    <TableCell className="max-w-[280px] truncate px-2 py-1.5">
                      {r.error ? (
                        <span className="text-red-600 dark:text-red-400">{r.error.slice(0, 60)}</span>
                      ) : (
                        r.question
                      )}
                    </TableCell>
                    <TableCell className="px-2 py-1.5">
                      <span className={r.mode === "hybrid" ? "text-emerald-600 dark:text-emerald-400" : "text-sky-600 dark:text-sky-400"}>
                        {r.mode === "hybrid" ? "hybrid" : "trad"}
                      </span>
                      {!r.answerable && (
                        <Badge variant="outline" className="ml-1 px-1 text-[8px] text-amber-600 dark:text-amber-400">
                          OoS
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-right font-mono tabular-nums">
                      {r.generation?.correctness != null ? r.generation.correctness.toFixed(2) : "—"}
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-right font-mono tabular-nums">
                      {r.generation?.faithfulness != null ? r.generation.faithfulness.toFixed(2) : "—"}
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-center">
                      <span
                        className={`inline-block rounded px-1.5 py-0.5 text-[9px] font-medium ${ABST_STYLE[r.generation?.abstention ?? "pending"] ?? "bg-muted text-muted-foreground"}`}
                      >
                        {r.generation?.abstention ?? "pending"}
                      </span>
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-right font-mono tabular-nums">
                      {r.retrieval?.hit4 != null ? r.retrieval.hit4.toFixed(0) : "—"}
                    </TableCell>
                    <TableCell className="px-2 py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                      {lat != null ? (lat > 1000 ? `${(lat / 1000).toFixed(1)}s` : `${Math.round(lat)}ms`) : "—"}
                    </TableCell>
                  </TableRow>
                  {isOpen && (
                    <TableRow key={`${r.id}-detail`} className="bg-muted/30 hover:bg-muted/30">
                      <TableCell colSpan={9} className="px-4 py-3">
                        <div className="grid gap-3 text-[11px] leading-relaxed lg:grid-cols-2">
                          <div className="space-y-2">
                            <div>
                              <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                                answer ({r.model || "—"}{r.mode === "hybrid" ? " · Jev-routed" : ""})
                              </p>
                              <p className="whitespace-pre-wrap rounded border bg-background p-2">
                                {r.answer || "(empty)"}
                              </p>
                            </div>
                            <div>
                              <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                                reference (ground truth)
                              </p>
                              <p className="rounded border bg-background p-2 text-muted-foreground">
                                {r.reference || "(unanswerable — correct behaviour is to abstain)"}
                              </p>
                            </div>
                            <div>
                              <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                                judge reason
                              </p>
                              <p className="rounded border bg-background p-2 text-muted-foreground">
                                {r.generation?.reason || "—"}
                              </p>
                            </div>
                          </div>
                          <div className="space-y-2">
                            <div>
                              <p className="mb-1 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">
                                retrieved files (final context)
                              </p>
                              <div className="flex flex-wrap gap-1">
                                {r.retrieved_files.length > 0 ? (
                                  r.retrieved_files.map((f, i) => (
                                    <Badge key={`${f}-${i}`} variant="secondary" className="px-1.5 font-mono text-[9px]">
                                      {shortFile(f)}
                                    </Badge>
                                  ))
                                ) : (
                                  <span className="text-muted-foreground">(none)</span>
                                )}
                              </div>
                              {r.mode === "hybrid" && r.pre_rerank_files.length > 0 && (
                                <p className="mt-1 text-[9px] text-muted-foreground">
                                  pre-rerank order: {r.pre_rerank_files.map(shortFile).join(" → ")}
                                </p>
                              )}
                            </div>
                            {r.mode === "hybrid" && (
                              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 rounded border bg-background p-2 font-mono text-[10px] tabular-nums">
                                <span className="text-muted-foreground">sufficiency</span>
                                <span className="text-right">{r.sufficiency_p != null ? r.sufficiency_p.toFixed(3) : "—"}</span>
                                <span className="text-muted-foreground">verification</span>
                                <span className="text-right">{r.verification_p != null ? r.verification_p.toFixed(3) : "—"}</span>
                                <span className="text-muted-foreground">routed model</span>
                                <span className="text-right">{r.routed_model || "—"}</span>
                              </div>
                            )}
                            {r.pairwise && (
                              <div className="rounded border bg-background p-2 text-[10px]">
                                <span className="text-muted-foreground">pairwise judge: </span>
                                <span className="font-medium">
                                  {r.pairwise.winner === "tie" ? "tie" : `${r.pairwise.winner} better`}
                                </span>
                                <span className="ml-1 text-muted-foreground">
                                  ({r.pairwise.position_consistent ? "position-consistent" : "inconsistent → tie"})
                                </span>
                              </div>
                            )}
                            <div className="rounded border bg-background p-2 font-mono text-[10px] tabular-nums">
                              {Object.entries(r.timings ?? {}).map(([k, v]) => (
                                <span key={k} className="mr-3 text-muted-foreground">
                                  {k.replace(/_ms$/, "")}:<span className="text-foreground">{v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`}</span>
                                </span>
                              ))}
                              <span className="mr-3 text-muted-foreground">
                                tokens:<span className="text-foreground">{r.tokens_in}↓ {r.tokens_out}↑</span>
                              </span>
                              <span className="text-muted-foreground">
                                cost:<span className="text-foreground">{r.cost_usd != null ? `$${r.cost_usd.toFixed(5)}` : "—"}</span>
                              </span>
                            </div>
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </div>
      {runStatus === "running" && (
        <p className="mt-2 flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> rows stream in as each question completes
        </p>
      )}
    </div>
  );
}

function shortScenario(id: string): string {
  return { techdocs: "techdocs", finance: "finance", policy: "policy", distractor: "distractor", multilingual: "multiling", outofscope: "out-of-scope" }[id] ?? id;
}
