/** Shared types mirroring the backend SSE protocol (backend/app/rag/pipelines.py).
 * The event schema is owned jointly with backend/AGENTS.md — update both sides. */

export type PipelineMode = "traditional" | "hybrid";
export type Mode = PipelineMode | "compare";

/** One System-One decision record (Jev noul/choice, or a System Two plan/rewrite step). */
export interface Decision {
  name: string;
  label: string;
  kind: string; // noul | choice | plan | rewrite
  question: string;
  answer: unknown; // noul: number p; choice: option; plan: string[]; rewrite: string
  probabilities?: Record<string, number> | null;
  confidence?: number | null;
  latency_ms: number;
  usage?: Record<string, number> | null;
}

export interface LiteChunk {
  rank?: number | null;
  chunk_id: string;
  filename: string;
  similarity: number;
  jev_score?: number | null;
  snippet: string;
}

export interface Citation {
  index: number;
  chunk_id: string;
  doc_id: string;
  filename: string;
  similarity: number;
  rerank_score?: number | null;
  snippet: string;
}

/** v2 routing decision: effort level (no_retrieval / single_pass / multi_step). */
export interface RoutingInfo {
  model: string;
  effort?: string;
  probabilities: Record<string, number>;
  confidence?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  mode?: PipelineMode;
  pending?: boolean;
  stage?: string;
  error?: string;
  pairKey?: string;
  createdAt?: string;

  model?: string;
  routing?: RoutingInfo;
  decisions?: Decision[];
  retrieved?: LiteChunk[];
  sources?: Citation[];
  timings?: Record<string, number>;

  latencyMs?: number;
  promptTokens?: number | null;
  completionTokens?: number | null;
  costUsd?: number | null;
  verification?: number | null;
  contextSufficiency?: number | null;
  /** v2 additions */
  qualityScore?: number | null;
  bestOf?: Record<string, number> | null;
  retried?: boolean;
}
