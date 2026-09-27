"use client";

import { Brain, CircuitBoard, Cpu, Database, Route, Search, ShieldCheck, Timer, X } from "lucide-react";

import { ModeBadge, ProbabilityBar, formatCost } from "@/components/jevrag/ui-bits";
import { useJevRag } from "@/lib/jevrag/store";
import type { ChatMessage, Decision } from "@/lib/jevrag/types";
import { cn } from "@/lib/utils";

function DecisionCard({ decision }: { decision: Decision }) {
  const isJev = decision.kind === "noul" || decision.kind === "choice";
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-1.5 flex items-center gap-1.5">
        {decision.name === "routing" ? (
          <Route className="h-3.5 w-3.5 text-emerald-600" />
        ) : decision.name === "verification" ? (
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
        ) : (
          <Cpu className="h-3.5 w-3.5 text-emerald-600" />
        )}
        <span className="text-xs font-semibold">{decision.label}</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {decision.latency_ms.toFixed(0)}ms
        </span>
      </div>
      <p className="mb-2 text-[11px] leading-snug text-muted-foreground">{decision.question}</p>

      {isJev && decision.probabilities && Object.keys(decision.probabilities).length > 0 && (
        <div className="space-y-1">
          {Object.entries(decision.probabilities)
            .sort((a, b) => b[1] - a[1])
            .map(([label, p]) => (
              <ProbabilityBar
                key={label}
                label={label}
                value={p}
                highlight={
                  decision.kind === "choice"
                    ? label === String(decision.answer)
                    : Object.entries(decision.probabilities!)
                        .sort((a, b) => b[1] - a[1])
                        .findIndex(([l]) => l === label) <
                      (decision.name === "rerank" ? 4 : 1)
                }
              />
            ))}
          {decision.confidence !== null && decision.confidence !== undefined && (
            <p className="pt-0.5 text-[10px] text-muted-foreground">
              confidence {decision.confidence.toFixed(2)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  children,
  defaultOpen = true,
}: {
  icon: typeof Brain;
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen} className="group rounded-lg border bg-background/40">
      <summary className="flex cursor-pointer select-none items-center gap-1.5 px-3 py-2 text-xs font-semibold">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        {title}
        <span className="ml-auto text-[10px] text-muted-foreground transition-transform group-open:rotate-90">
          ›
        </span>
      </summary>
      <div className="space-y-2 px-3 pb-3">{children}</div>
    </details>
  );
}

export function TracePanelContent({ message }: { message: ChatMessage }) {
  const decisions = message.decisions ?? [];
  const retrieved = message.retrieved ?? [];
  const sources = message.sources ?? [];
  const timings = message.timings ?? {};

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <ModeBadge mode={message.mode ?? "traditional"} />
        {message.model && <span className="font-mono text-[11px] text-muted-foreground">{message.model}</span>}
      </div>

      {decisions.length > 0 && (
        <Section icon={Brain} title={`System One · Jev-style decisions (${decisions.length})`}>
          {decisions.map((d, i) => (
            <DecisionCard key={`${d.name}-${i}`} decision={d} />
          ))}
        </Section>
      )}

      {retrieved.length > 0 && (
        <Section icon={Search} title={`Retrieved passages (${retrieved.length})`}>
          {retrieved.map((c, i) => (
            <div key={c.chunk_id ?? i} className="rounded-md border bg-card p-2">
              <div className="mb-1 flex items-center gap-2 text-[11px]">
                <span className="font-mono font-semibold text-muted-foreground">
                  #{c.rank ?? i + 1}
                </span>
                <span className="min-w-0 flex-1 truncate">{c.filename}</span>
                {c.jev_score !== null && c.jev_score !== undefined && (
                  <span
                    className="rounded bg-emerald-600/10 px-1 font-mono text-[10px] text-emerald-700 dark:text-emerald-400"
                    title="Jev calibrated relevance"
                  >
                    jev {c.jev_score.toFixed(2)}
                  </span>
                )}
              </div>
              <p className="line-clamp-2 text-[10px] leading-snug text-muted-foreground">{c.snippet}</p>
              <div className="mt-1">
                <ProbabilityBar
                  label="similarity"
                  value={c.similarity}
                  max={Math.max(...retrieved.map((x) => x.similarity), 0.01)}
                  suffix={c.similarity.toFixed(2)}
                />
              </div>
            </div>
          ))}
        </Section>
      )}

      {sources.length > 0 && (
        <Section icon={Database} title={`Cited sources (${sources.length})`} defaultOpen={false}>
          {sources.map((s) => (
            <div key={s.chunk_id} className="rounded-md border bg-card p-2">
              <div className="mb-1 flex items-center gap-2 text-[11px]">
                <span className="inline-flex h-4 min-w-4 items-center justify-center rounded bg-emerald-600/15 px-1 font-mono text-[10px] font-semibold text-emerald-700 dark:text-emerald-400">
                  {s.index}
                </span>
                <span className="min-w-0 flex-1 truncate">{s.filename}</span>
              </div>
              <p className="line-clamp-3 text-[10px] leading-snug text-muted-foreground">{s.snippet}</p>
            </div>
          ))}
        </Section>
      )}

      <Section icon={CircuitBoard} title="System Two · generation">
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
          <span className="text-muted-foreground">Model</span>
          <span className="truncate font-mono text-right">{message.model ?? "—"}</span>
          <span className="text-muted-foreground">Latency</span>
          <span className="font-mono text-right">
            {message.latencyMs ? `${(message.latencyMs / 1000).toFixed(1)}s` : "—"}
          </span>
          <span className="text-muted-foreground">Tokens</span>
          <span className="font-mono text-right">
            {message.promptTokens !== undefined ? `${message.promptTokens}→${message.completionTokens ?? "?"}` : "—"}
          </span>
          <span className="text-muted-foreground">Est. cost</span>
          <span className="font-mono text-right">{formatCost(message.costUsd)}</span>
        </div>
      </Section>

      {Object.keys(timings).length > 0 && (
        <Section icon={Timer} title="Timings" defaultOpen={false}>
          <div className="space-y-1">
            {Object.entries(timings)
              .sort((a, b) => b[1] - a[1])
              .map(([k, v]) => (
                <div key={k} className="flex items-center justify-between text-[11px]">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="font-mono tabular-nums">{v.toFixed(0)} ms</span>
                </div>
              ))}
          </div>
        </Section>
      )}
    </div>
  );
}

/** The right-side trace panel; renders the active message's pipeline trace. */
export function TracePanel({ className }: { className?: string }) {
  const { traceOpen, traceMessageId, messages, streaming, closeTrace } = useJevRag();
  const message =
    messages.find((m) => m.id === traceMessageId) ??
    (streaming ? [...messages].reverse().find((m) => m.role === "assistant") : undefined);

  if (!traceOpen || !message) return null;

  return (
    <aside className={cn("flex h-full w-full flex-col border-l bg-background/60", className)}>
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold">Pipeline trace</h2>
        <button
          type="button"
          onClick={closeTrace}
          className="rounded-md p-1 text-muted-foreground hover:bg-muted"
          aria-label="Close trace panel"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <TracePanelContent message={message} />
      </div>
    </aside>
  );
}
