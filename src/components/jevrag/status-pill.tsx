"use client";

import { useEffect, useState } from "react";
import { Cloud, Cpu, Database } from "lucide-react";
import { toast } from "sonner";

import { useJevRag } from "@/lib/jevrag/store";
import { cn } from "@/lib/utils";

function Dot({ ok }: { ok: boolean | undefined }) {
  if (ok === undefined) {
    return <span className="h-2 w-2 rounded-full bg-zinc-400 animate-pulse" />;
  }
  return (
    <span
      className={cn(
        "h-2 w-2 rounded-full",
        ok ? "bg-emerald-500" : "bg-red-500",
      )}
    />
  );
}

export function StatusPill() {
  const status = useJevRag((s) => s.status);
  const refreshStatus = useJevRag((s) => s.refreshStatus);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    void refreshStatus();
    const t = setInterval(() => void refreshStatus(), 45_000);
    return () => clearInterval(t);
  }, [refreshStatus]);

  const cloudOk = status?.dashscope?.ok;
  const jevOk = status?.jev?.ok;
  const docsReady = status?.documents?.ready ?? 0;
  const chunks = status?.vector_store?.chunks ?? 0;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full border bg-background/80 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted/60"
        aria-label="System status"
      >
        <span className="flex items-center gap-1" title="Cloud LLM (Dashscope)">
          <Cloud className="h-3.5 w-3.5" />
          <Dot ok={cloudOk} />
        </span>
        <span className="flex items-center gap-1" title="Local Jev-style engine">
          <Cpu className="h-3.5 w-3.5" />
          <Dot ok={jevOk} />
        </span>
        <span className="flex items-center gap-1" title="Indexed documents">
          <Database className="h-3.5 w-3.5" />
          <span className="font-mono tabular-nums">{docsReady}</span>
        </span>
      </button>

      {open && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
            aria-label="Close status"
          />
          <div className="absolute right-0 z-50 mt-2 w-80 rounded-lg border bg-popover p-4 text-popover-foreground shadow-lg">
            <p className="mb-3 text-sm font-semibold">System status</p>
            <ul className="space-y-2.5 text-xs">
              <li className="flex items-start justify-between gap-2">
                <span className="text-muted-foreground">Cloud LLM (System Two)</span>
                <span className="text-right">
                  {cloudOk ? (
                    <span className="font-mono">{status?.config?.llm_model_default}</span>
                  ) : (
                    <span className="text-red-500">{status?.dashscope?.error ?? "unreachable"}</span>
                  )}
                </span>
              </li>
              <li className="flex items-start justify-between gap-2">
                <span className="text-muted-foreground">Local Jev engine (System One)</span>
                <span className="text-right">
                  {jevOk ? (
                    <>
                      <span className="font-mono">{status?.jev?.model}</span>
                      <span className="block text-[10px] text-muted-foreground">
                        {status?.jev?.backend} · {status?.jev?.quant} · loaded in{" "}
                        {status?.jev?.load_seconds}s
                      </span>
                    </>
                  ) : (
                    <span className="text-red-500">{status?.jev?.error ?? "not loaded"}</span>
                  )}
                </span>
              </li>
              <li className="flex items-start justify-between gap-2">
                <span className="text-muted-foreground">Embeddings</span>
                <span className="font-mono text-right">
                  {status?.embeddings?.model ?? "—"}
                  {!status?.embeddings?.ok && (
                    <span className="block text-red-500">{status?.embeddings?.error}</span>
                  )}
                </span>
              </li>
              <li className="flex items-start justify-between gap-2">
                <span className="text-muted-foreground">Vector store</span>
                <span className="font-mono">{chunks} chunks</span>
              </li>
              <li className="flex items-start justify-between gap-2">
                <span className="text-muted-foreground">Retrieval</span>
                <span className="font-mono">
                  top-{status?.config?.top_k_retrieve} → keep {status?.config?.top_k_use}
                </span>
              </li>
            </ul>
            <button
              type="button"
              className="mt-3 w-full rounded-md border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted"
              onClick={async () => {
                await navigator.clipboard
                  ?.writeText(JSON.stringify(status, null, 2))
                  .then(() => {
                    setCopied(true);
                    toast.success("Status JSON copied");
                    setTimeout(() => setCopied(false), 1500);
                  })
                  .catch(() => toast.error("Clipboard unavailable"));
              }}
            >
              {copied ? "Copied!" : "Copy status JSON"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
