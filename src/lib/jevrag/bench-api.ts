/** Bench API client: scenario catalog, run lifecycle, results (via /backend-api rewrite). */

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/backend-api${path}`, init);
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export interface ScenarioMeta {
  id: string;
  name: string;
  category: string;
  description: string;
  stresses: string;
  doc_count: number;
  question_count: number;
  answerable: number;
  unanswerable: number;
  qtypes: string[];
}

export interface BenchRunInfo {
  id: string;
  label: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
  scenario_ids: string[];
  judge_model: string;
  config: Record<string, unknown> | null;
  progress: { done: number; total: number; stage: string };
  created_at: string;
  started_at: string;
  finished_at: string;
  error?: string | null;
}

export interface ArmMetrics {
  n: number;
  correctness: number | null;
  faithfulness: number | null;
  abstention: Record<string, number>;
  retrieval: Record<string, number>;
  latency_ms: { mean: number | null; p50: number | null; p95: number | null };
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  errors: number;
  sufficiency_mean?: number | null;
  verification_mean?: number | null;
  rerank_lift?: Record<string, number>;
}

export interface PairwiseMetrics {
  n: number;
  hybrid_wins: number;
  traditional_wins: number;
  ties: number;
  hybrid_win_rate: number;
  position_consistency: number;
}

export interface BenchSummary {
  scenarios: Record<
    string,
    {
      name: string;
      questions: number;
      traditional: ArmMetrics;
      hybrid: ArmMetrics;
      pairwise: PairwiseMetrics | Record<string, never>;
    }
  >;
  overall: {
    questions: number;
    traditional: ArmMetrics;
    hybrid: ArmMetrics;
    pairwise: PairwiseMetrics | Record<string, never>;
  };
  abstention_analysis: Record<string, { n: number } & Record<string, number | null>>;
  gate_analysis: { n?: number; accuracy?: number; brier?: number } | Record<string, never>;
  judge: { model: string; selftest_agreement: number | null };
  generated_at: string;
}

export interface BenchResultRow {
  id: string;
  run_id: string;
  scenario_id: string;
  question_id: string;
  question: string;
  mode: "traditional" | "hybrid";
  qtype: string;
  answerable: boolean;
  reference: string;
  answer: string;
  model: string;
  error?: string | null;
  retrieved_files: string[];
  pre_rerank_files: string[];
  retrieval: Record<string, number>;
  naive_retrieval: Record<string, number>;
  generation: {
    correctness?: number | null;
    faithfulness?: number | null;
    abstention?: string;
    reason?: string;
    judge_error?: boolean;
  };
  pairwise: { winner: string; position_consistent: boolean } | null;
  timings: Record<string, number>;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number | null;
  sufficiency_p: number | null;
  verification_p: number | null;
  routed_model: string | null;
}

export interface RunDetail {
  run: BenchRunInfo & { judge_selftest: unknown; summary: BenchSummary | null };
  results: BenchResultRow[];
}

export const benchApi = {
  scenarios: () => fetchJSON<{ scenarios: ScenarioMeta[] }>("/bench/scenarios"),
  runs: () => fetchJSON<{ runs: BenchRunInfo[]; runner_active: boolean }>("/bench/runs"),
  run: (id: string) => fetchJSON<RunDetail>(`/bench/runs/${id}`),
  startRun: (scenarioIds: string[], label: string) =>
    fetchJSON<{ run: BenchRunInfo }>("/bench/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_ids: scenarioIds, label }),
    }),
  deleteRun: (id: string) => fetchJSON<{ deleted: string }>(`/bench/runs/${id}`, { method: "DELETE" }),
};
