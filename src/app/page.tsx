"use client";

import { useEffect, useState } from "react";
import { Activity, FlaskConical, Loader2, Menu, MessageSquare, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { BenchView } from "@/components/jevrag/bench/bench-view";
import { ChatPanel } from "@/components/jevrag/chat-panel";
import { Sidebar } from "@/components/jevrag/sidebar";
import { StatusPill } from "@/components/jevrag/status-pill";
import { TracePanel } from "@/components/jevrag/trace-panel";
import { useJevRag } from "@/lib/jevrag/store";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const MODES = [
  { value: "traditional", label: "Traditional", short: "Trad" },
  { value: "hybrid", label: "Hybrid · Jev", short: "Jev" },
  { value: "compare", label: "Compare", short: "Cmp" },
] as const;

function LogoMark() {
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-lg border bg-card">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden="true">
        <path
          d="M4 17.5 8 9l4 5.5L16 6l4 8"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-emerald-600"
        />
      </svg>
    </span>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      aria-label="Toggle theme"
      className="h-8 w-8"
    >
      <Sun className="h-4 w-4 dark:hidden" />
      <Moon className="hidden h-4 w-4 dark:block" />
    </Button>
  );
}

export default function Home() {
  const { init, mode, setMode, streaming, traceOpen, messages } = useJevRag();
  const [booting, setBooting] = useState(true);
  const [view, setView] = useState<"chat" | "bench">("chat");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await init();
      if (!cancelled) setBooting(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [init]);

  const hasTraceable = messages.some((m) => m.role === "assistant");

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* Header */}
      <header className="flex shrink-0 items-center gap-2 border-b bg-background/80 px-3 py-2 backdrop-blur sm:gap-3 sm:px-4">
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8 lg:hidden" aria-label="Open menu">
              <Menu className="h-4 w-4" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 p-0 lg:hidden">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <Sidebar />
          </SheetContent>
        </Sheet>

        <div className="hidden items-center gap-2 sm:flex">
          <LogoMark />
          <div className="leading-tight">
            <p className="text-sm font-semibold">Jev-RAG</p>
            <p className="text-[10px] text-muted-foreground">local-first hybrid retrieval</p>
          </div>
        </div>

        <div className="mx-auto flex items-center gap-3">
          {/* top-level view switch */}
          <div className="flex items-center rounded-lg border bg-muted/40 p-0.5">
            {([
              { v: "chat", label: "Chat", icon: MessageSquare },
              { v: "bench", label: "Benchmarks", icon: FlaskConical },
            ] as const).map(({ v, label, icon: Icon }) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors sm:px-3 sm:text-[12px] ${
                  view === v
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                aria-label={`Switch to ${label}`}
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </div>

          {view === "chat" && (
            <Tabs value={mode} onValueChange={(v) => setMode(v as typeof mode)}>
              <TabsList className="h-8 sm:h-9">
                {MODES.map((m) => (
                  <TabsTrigger
                    key={m.value}
                    value={m.value}
                    disabled={streaming}
                    className="gap-0 px-2 text-[11px] sm:px-3 sm:text-[13px]"
                  >
                    <span className="hidden sm:inline">{m.label}</span>
                    <span className="sm:hidden">{m.short}</span>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          )}
        </div>

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          {booting && (
            <span className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> waking local models…
            </span>
          )}
          <StatusPill />
          <Sheet>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 xl:hidden"
                aria-label="Open trace panel"
                disabled={!hasTraceable}
              >
                <Activity className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-[22rem] p-0 xl:hidden">
              <SheetTitle className="sr-only">Pipeline trace</SheetTitle>
              <TracePanel />
            </SheetContent>
          </Sheet>
          <ThemeToggle />
        </div>
      </header>

      {/* Body */}
      {view === "bench" ? (
        <main className="flex min-w-0 flex-1 flex-col">
          <BenchView />
        </main>
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="hidden w-72 shrink-0 border-r lg:block">
            <Sidebar />
          </div>

          <main className="flex min-w-0 flex-1 flex-col">
            <ChatPanel />
          </main>

          {traceOpen && (
            <div className="hidden w-96 shrink-0 xl:block">
              <TracePanel />
            </div>
          )}
        </div>
      )}

      {/* Footer (sticky, pushed down naturally on overflow) */}
      <footer className="flex shrink-0 items-center justify-between gap-2 border-t bg-background px-4 py-1.5 text-[10px] text-muted-foreground">
        <span>Jev-RAG · System One (local Jev-style) + System Two (cloud LLM)</span>
        <span className="hidden sm:inline">
          Fully local stack — ChromaDB · fastembed · llama.cpp · FastAPI · Next.js
        </span>
      </footer>
    </div>
  );
}
