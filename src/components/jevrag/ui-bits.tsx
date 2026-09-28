"use client";

/** Small shared UI atoms for the Jev-RAG interface. */

import { FileText, Gauge, Layers, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

export function ModeBadge({ mode, className }: { mode: string; className?: string }) {
  const hybrid = mode === "hybrid";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        hybrid
          ? "border-emerald-600/40 bg-emerald-600/10 text-emerald-700 dark:text-emerald-400"
          : "border-amber-600/40 bg-amber-600/10 text-amber-700 dark:text-amber-400",
        className,
      )}
    >
      {hybrid ? <Sparkles className="h-3 w-3" /> : <Layers className="h-3 w-3" />}
      {hybrid ? "Hybrid · Jev" : "Traditional"}
    </span>
  );
}

export function ProbabilityBar({
  label,
  value,
  max = 1,
  highlight = false,
  suffix,
}: {
  label: string;
  value: number;
  max?: number;
  highlight?: boolean;
  suffix?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="flex items-center gap-2">
      <span className="w-24 shrink-0 truncate text-xs text-muted-foreground" title={label}>
        {label}
      </span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            highlight ? "bg-emerald-500" : "bg-zinc-400 dark:bg-zinc-600",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-12 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
        {suffix ?? value.toFixed(2)}
      </span>
    </div>
  );
}

export function CitationChip({
  label,
  onClick,
}: {
  label: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mx-0.5 inline-flex h-4 min-w-4 -translate-y-1 items-center justify-center rounded bg-emerald-600/15 px-1 align-baseline font-mono text-[10px] font-semibold text-emerald-700 transition-colors hover:bg-emerald-600/30 dark:text-emerald-400"
      title={`View source ${label}`}
    >
      {label}
    </button>
  );
}

const STAGE_ICONS: Record<string, typeof Gauge> = {
  retrieving: Gauge,
  "jev-reranking": Sparkles,
  "jev-routing": Sparkles,
  "jev-verifying": Sparkles,
  answering: FileText,
};

export function StageIndicator({ stage }: { stage?: string }) {
  if (!stage) return null;
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
      </span>
      {stage}
    </div>
  );
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "—";
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(3)}`;
}
