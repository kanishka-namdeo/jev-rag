"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Layers, Loader2, Sparkles, Square } from "lucide-react";

import { ChatMessageView } from "@/components/jevrag/chat-message";
import { useJevRag } from "@/lib/jevrag/store";
import type { ChatMessage } from "@/lib/jevrag/types";
import { cn } from "@/lib/utils";

const MODE_HINTS: Record<string, string> = {
  traditional:
    "Traditional RAG — embedding retrieval → cloud LLM (qwen3.7-plus) directly answers with citations.",
  hybrid:
    "Hybrid RAG — the local Jev-style engine reranks passages, checks sufficiency and routes between qwen3.7-plus / qwen3.6-plus before the cloud LLM answers; the answer is then verified for groundedness.",
  compare: "Compare — runs both pipelines side by side on the same question.",
};

const SUGGESTIONS = [
  "What are the main topics covered in my documents?",
  "Summarize the most important points with citations.",
  "What limitations or risks are mentioned?",
];

function EmptyState() {
  const { setMode, documents } = useJevRag();
  const readyDocs = documents.filter((d) => d.status === "ready").length;

  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center gap-6 py-10 text-center sm:py-16">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Jev-RAG</h1>
        <p className="mt-2 text-sm text-muted-foreground sm:text-base">
          Two retrieval-augmented pipelines over your own documents:
        </p>
      </div>
      <div className="grid w-full gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => setMode("traditional")}
          className="rounded-xl border border-amber-600/30 bg-amber-600/5 p-4 text-left transition-colors hover:bg-amber-600/10"
        >
          <span className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
            <Layers className="h-4 w-4 text-amber-600" /> Traditional RAG
          </span>
          <span className="text-xs leading-relaxed text-muted-foreground">
            Embedding search feeds the cloud LLM directly. Simple, fast, one model.
          </span>
        </button>
        <button
          type="button"
          onClick={() => setMode("hybrid")}
          className="rounded-xl border border-emerald-600/30 bg-emerald-600/5 p-4 text-left transition-colors hover:bg-emerald-600/10"
        >
          <span className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
            <Sparkles className="h-4 w-4 text-emerald-600" /> Hybrid · Jev-style
          </span>
          <span className="text-xs leading-relaxed text-muted-foreground">
            A local calibrated decision model (System One) reranks, gates and routes; the cloud LLM
            (System Two) writes; answers get a groundedness score.
          </span>
        </button>
      </div>
      {readyDocs === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-xs text-muted-foreground">
          Upload documents in the sidebar first — answers are grounded only in your files.
        </p>
      ) : (
        <div className="flex flex-wrap justify-center gap-2">
          {SUGGESTIONS.map((s) => (
            <SuggestionChip key={s} text={s} />
          ))}
        </div>
      )}
    </div>
  );
}

function SuggestionChip({ text }: { text: string }) {
  const send = useJevRag((s) => s.send);
  return (
    <button
      type="button"
      onClick={() => void send(text)}
      className="rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted"
    >
      {text}
    </button>
  );
}

function CompareRow({ left, right }: { left: ChatMessage; right: ChatMessage }) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="min-w-0">
        <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400">
          <Layers className="h-3 w-3" /> Traditional
        </p>
        <ChatMessageView message={left} />
      </div>
      <div className="min-w-0">
        <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
          <Sparkles className="h-3 w-3" /> Hybrid · Jev
        </p>
        <ChatMessageView message={right} />
      </div>
    </div>
  );
}

function MessageList() {
  const messages = useJevRag((s) => s.messages);
  const streaming = useJevRag((s) => s.streaming);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastLen = useRef(0);

  useEffect(() => {
    const contentLen = messages.reduce((n, m) => n + m.content.length, 0);
    if (contentLen !== lastLen.current) {
      lastLen.current = contentLen;
      bottomRef.current?.scrollIntoView({ behavior: contentLen > 2000 ? "auto" : "smooth" });
    }
  }, [messages]);

  const rendered: React.ReactNode[] = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (m.role === "assistant" && m.pairKey) {
      const next = messages[i + 1];
      if (next?.pairKey === m.pairKey) {
        rendered.push(<CompareRow key={m.id} left={m} right={next} />);
        i++;
        continue;
      }
    }
    rendered.push(<ChatMessageView key={m.id} message={m} />);
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-6">
      {rendered}
      <div ref={bottomRef} className={cn("h-2", streaming && "animate-pulse")} />
    </div>
  );
}

export function ChatPanel() {
  const { messages, send, streaming, mode } = useJevRag();
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    void send(text);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const pendingStage = [...messages].reverse().find((m) => m.pending)?.stage;

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? <EmptyState /> : <MessageList />}
      </div>

      <div className="border-t bg-background/80 backdrop-blur">
        <div className="mx-auto w-full max-w-3xl px-4 py-3">
          {pendingStage && (
            <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-emerald-600" />
              {pendingStage}
            </div>
          )}
          <div className="flex items-end gap-2 rounded-xl border bg-background p-2 focus-within:ring-1 focus-within:ring-ring">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                const el = e.target as HTMLTextAreaElement;
                el.style.height = "auto";
                el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              rows={1}
              placeholder={
                messages.length === 0
                  ? "Ask anything about your documents…"
                  : "Follow up…"
              }
              className="max-h-40 min-h-[36px] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
              disabled={streaming}
            />
            <button
              type="button"
              onClick={submit}
              disabled={!input.trim() || streaming}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
              aria-label="Send message"
            >
              {streaming ? (
                <Square className="h-4 w-4" />
              ) : (
                <ArrowUp className="h-4 w-4" />
              )}
            </button>
          </div>
          <p className="mt-1.5 px-1 text-[11px] leading-snug text-muted-foreground">
            {MODE_HINTS[mode]} <span className="opacity-70">Enter to send · Shift+Enter for a new line</span>
          </p>
        </div>
      </div>
    </div>
  );
}
