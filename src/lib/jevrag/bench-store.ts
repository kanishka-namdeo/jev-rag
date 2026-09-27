"use client";

/** Bench store: scenario catalog, runs list, selected run detail, live polling. */

import { toast } from "sonner";
import { create } from "zustand";

import {
  benchApi,
  type BenchResultRow,
  type BenchRunInfo,
  type BenchSummary,
  type RunDetail,
  type ScenarioMeta,
} from "@/lib/jevrag/bench-api";

const POLL_MS = 3000;

interface BenchState {
  scenarios: ScenarioMeta[];
  selected: string[];               // scenario ids chosen for the next run
  runs: BenchRunInfo[];
  runnerActive: boolean;
  activeRunId: string | null;       // running/queued run being polled
  selectedRunId: string | null;     // run shown in the results dashboard
  detail: RunDetail | null;         // detail of selectedRunId
  loading: boolean;
  starting: boolean;
  filterMode: "all" | "traditional" | "hybrid";
  filterScenario: string;           // "" = all scenarios

  init: () => Promise<void>;
  toggleScenario: (id: string) => void;
  selectAllScenarios: () => void;
  startRun: () => Promise<void>;
  refreshRuns: () => Promise<void>;
  selectRun: (id: string | null) => Promise<void>;
  loadDetail: (id: string) => Promise<void>;
  deleteRun: (id: string) => Promise<void>;
  setFilterMode: (m: "all" | "traditional" | "hybrid") => void;
  setFilterScenario: (s: string) => void;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

export const useBench = create<BenchState>((set, get) => ({
  scenarios: [],
  selected: [],
  runs: [],
  runnerActive: false,
  activeRunId: null,
  selectedRunId: null,
  detail: null,
  loading: false,
  starting: false,
  filterMode: "all",
  filterScenario: "",

  init: async () => {
    set({ loading: true });
    try {
      const [scen, runs] = await Promise.all([benchApi.scenarios(), benchApi.runs()]);
      const active = runs.runs.find((r) => ["queued", "running", "cancelling"].includes(r.status));
      const completed = runs.runs.find((r) => r.status === "completed");
      const showId = active?.id ?? completed?.id ?? runs.runs[0]?.id ?? null;
      set({
        scenarios: scen.scenarios,
        selected: scen.scenarios.map((s) => s.id),
        runs: runs.runs,
        runnerActive: runs.runner_active,
        activeRunId: active?.id ?? null,
        selectedRunId: showId,
      });
      if (showId) await get().loadDetail(showId);
      if (active) startPolling(active.id);
    } catch (e) {
      toast.error(`Bench init failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      set({ loading: false });
    }
  },

  toggleScenario: (id) =>
    set((s) => ({
      selected: s.selected.includes(id)
        ? s.selected.filter((x) => x !== id)
        : [...s.selected, id],
    })),

  selectAllScenarios: () => set((s) => ({ selected: s.scenarios.map((x) => x.id) })),

  startRun: async () => {
    const { selected, runs, starting } = get();
    if (starting || selected.length === 0) return;
    const running = runs.find((r) => ["queued", "running", "cancelling"].includes(r.status));
    if (running) {
      toast.error("A run is already in progress — wait for it to finish.");
      return;
    }
    set({ starting: true });
    try {
      const label = `run ${new Date().toLocaleString()} · ${selected.length} scenario(s)`;
      const { run } = await benchApi.startRun(selected, label);
      toast.success("Benchmark run started");
      set({ activeRunId: run.id, selectedRunId: run.id, detail: null });
      await get().refreshRuns();
      startPolling(run.id);
    } catch (e) {
      toast.error(`Failed to start run: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      set({ starting: false });
    }
  },

  refreshRuns: async () => {
    try {
      const { runs, runnerActive: ra } = await benchApi.runs();
      set({ runs, runnerActive: ra });
      const active = runs.find((r) => ["queued", "running", "cancelling"].includes(r.status));
      set({ activeRunId: active?.id ?? null });
    } catch {
      /* transient — polling retries */
    }
  },

  selectRun: async (id) => {
    set({ selectedRunId: id, detail: null });
    if (id) await get().loadDetail(id);
  },

  loadDetail: async (id) => {
    try {
      const detail = await benchApi.run(id);
      set({ detail, selectedRunId: id });
    } catch (e) {
      toast.error(`Failed to load run: ${e instanceof Error ? e.message : String(e)}`);
    }
  },

  deleteRun: async (id) => {
    try {
      await benchApi.deleteRun(id);
      toast.success("Run deleted");
      if (get().selectedRunId === id) set({ selectedRunId: null, detail: null });
      await get().refreshRuns();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  },

  setFilterMode: (m) => set({ filterMode: m }),
  setFilterScenario: (s) => set({ filterScenario: s }),
}));

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPolling(runId: string) {
  stopPolling();
  pollTimer = setInterval(async () => {
    const st = useBench.getState();
    try {
      if (st.selectedRunId === runId || st.activeRunId === runId) {
        await st.loadDetail(runId);
      }
      await st.refreshRuns();
      const run = useBench.getState().runs.find((r) => r.id === runId);
      if (!run || !["queued", "running", "cancelling"].includes(run.status)) {
        stopPolling();
        if (run?.status === "completed") {
          toast.success("Benchmark run completed");
          await useBench.getState().loadDetail(runId);
        } else if (run?.status === "failed") {
          toast.error(`Benchmark run failed: ${run.error ?? "unknown error"}`);
        }
      }
    } catch {
      /* transient */
    }
  }, POLL_MS);
}

/** Convenience selectors */
export function useFilteredResults(): BenchResultRow[] {
  return useBench((s) => {
    const detail = s.detail;
    if (!detail) return [];
    let rows = detail.results;
    if (s.filterMode !== "all") rows = rows.filter((r) => r.mode === s.filterMode);
    if (s.filterScenario) rows = rows.filter((r) => r.scenario_id === s.filterScenario);
    return rows;
  });
}

export function useSummary(): BenchSummary | null {
  return useBench((s) => s.detail?.run.summary ?? null);
}
