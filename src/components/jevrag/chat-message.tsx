"use client";

import { Fragment, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { AlertCircle, BadgeCheck, ShieldQuestion, Zap } from "lucide-react";

import { CitationChip, ModeBadge, StageIndicator, formatCost } from "@/components/jevrag/ui-bits";
import { useJevRag } from "@/lib/jevrag/store";
import type { ChatMessage } from "@/lib/jevrag/types";
import { cn } from "@/lib/utils";

/** Render plain text, turning [1] / [2][3] citations into clickable chips. */
function withCitations(node: ReactNode, onCite?: (n: number) => void): ReactNode {
  if (typeof node === "string") {
    const parts = node.split(/(\[\d+(?:,\s*\d+)*\])/g);
    return parts.map((part, i) => {
      const m = part.match(/^\[(\d+(?:,\s*\d+)*)\]$/);
      if (m) {
        return (
          <CitationChip
            key={i}
            label={m[1]}
            onClick={() => onCite?.(Number(m[1].split(",")[0]))}
          />
        );
      }
      return <Fragment key={i}>{part}</Fragment>;
    });
  }
  if (Array.isArray(node)) return node.map((child, i) => <Fragment key={i}>{withCitations(child, onCite)}</Fragment>);
  return node;
}

function VerificationBadge({ p }: { p: number }) {
  const ok = p >= 0.7;
  const mid = p >= 0.4;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        ok
          ? "border-emerald-600/40 bg-emerald-600/10 text-emerald-700 dark:text-emerald-400"
          : mid
            ? "border-amber-600/40 bg-amber-600/10 text-amber-700 dark:text-amber-400"
            : "border-red-600/40 bg-red-600/10 text-red-700 dark:text-red-400",
      )}
      title={`Jev groundedness check: P(supported) = ${p}`}
    >
      {ok ? <BadgeCheck className="h-3 w-3" /> : mid ? <ShieldQuestion className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
      grounded {(p * 100).toFixed(0)}%
    </span>
  );
}

export function ChatMessageView({ message }: { message: ChatMessage }) {
  const openTrace = useJevRag((s) => s.openTrace);
  const onCite = () => openTrace(message.id);

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm text-primary-foreground sm:max-w-[75%]">
          {message.content}
        </div>
      </div>
    );
  }

  const isHybrid = message.mode === "hybrid";
  const hasTrace = Boolean(message.decisions?.length || message.retrieved?.length);

  return (
    <article
      className={cn(
        "rounded-xl border bg-card p-4 shadow-sm",
        isHybrid ? "border-emerald-600/20" : "border-amber-600/20",
      )}
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <ModeBadge mode={message.mode ?? "traditional"} />
        {message.model && (
          <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-mono text-muted-foreground">
            <Zap className="h-3 w-3" /> {message.model}
          </span>
        )}
        {message.contextSufficiency !== null && message.contextSufficiency !== undefined && (
          <span
            className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground"
            title="Jev sufficiency gate: P(context is sufficient)"
          >
            context {message.contextSufficiency.toFixed(2)}
          </span>
        )}
        {message.pending && <StageIndicator stage={message.stage} />}
      </header>

      {message.error ? (
        <div className="flex items-start gap-2 rounded-lg border border-red-600/30 bg-red-600/5 p-3 text-sm text-red-600 dark:text-red-400">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="min-w-0 break-words">{message.error}</span>
        </div>
      ) : (
        <div className="prose-jevrag text-sm leading-relaxed">
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="mb-3 last:mb-0">{withCitations(children, onCite)}</p>,
              li: ({ children }) => (
                <li className="mb-1 ml-4 list-disc marker:text-muted-foreground">
                  {withCitations(children, onCite)}
                </li>
              ),
              code: ({ className, children }) => {
                const isBlock = /language-/.test(className ?? "");
                if (isBlock) {
                  return (
                    <code className="block overflow-x-auto rounded-lg border bg-muted/50 p-3 font-mono text-xs">
                      {children}
                    </code>
                  );
                }
                return (
                  <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{children}</code>
                );
              },
              pre: ({ children }) => <pre className="mb-3">{children}</pre>,
              h1: ({ children }) => <h3 className="mb-2 mt-3 text-base font-semibold">{children}</h3>,
              h2: ({ children }) => <h3 className="mb-2 mt-3 text-base font-semibold">{children}</h3>,
              h3: ({ children }) => <h4 className="mb-2 mt-2 text-sm font-semibold">{children}</h4>,
              a: ({ children, href }) => (
                <a href={href} target="_blank" rel="noreferrer" className="text-emerald-700 underline dark:text-emerald-400">
                  {children}
                </a>
              ),
              blockquote: ({ children }) => (
                <blockquote className="mb-3 border-l-2 border-muted-foreground/30 pl-3 text-muted-foreground">
                  {children}
                </blockquote>
              ),
              table: ({ children }) => (
                <div className="mb-3 overflow-x-auto">
                  <table className="w-full text-xs">{children}</table>
                </div>
              ),
            }}
          >
            {message.content || (message.pending ? "" : "_No content returned._")}
          </ReactMarkdown>
        </div>
      )}

      {message.pending && !message.content && !message.error && (
        <div className="flex items-center gap-1.5 py-1">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:0ms]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:300ms]" />
        </div>
      )}

      <footer className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted-foreground">
        {message.verification !== null && message.verification !== undefined && (
          <VerificationBadge p={message.verification} />
        )}
        {message.latencyMs !== undefined && (
          <span className="font-mono tabular-nums">{(message.latencyMs / 1000).toFixed(1)}s</span>
        )}
        {message.completionTokens !== undefined && message.completionTokens !== null && (
          <span className="font-mono tabular-nums" title="prompt / completion tokens">
            {message.promptTokens ?? "?"}→{message.completionTokens} tok
          </span>
        )}
        {message.costUsd !== undefined && (
          <span className="font-mono tabular-nums" title="estimated cost">
            {formatCost(message.costUsd)}
          </span>
        )}
        {message.sources && message.sources.length > 0 && (
          <span className="font-mono tabular-nums">{message.sources.length} sources</span>
        )}
        {hasTrace && (
          <button
            type="button"
            onClick={() => openTrace(message.id)}
            className="ml-auto rounded-full border px-2.5 py-0.5 font-medium text-muted-foreground transition-colors hover:bg-muted"
          >
            View trace
          </button>
        )}
      </footer>
    </article>
  );
}
