/** API client: all backend requests go through the Next.js rewrite
 * (/backend-api/* -> FastAPI :8000), so relative URLs work both directly
 * (localhost:3000) and through the sandbox gateway. */

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/backend-api${path}`, init);
  if (!resp.ok) {
    let detail = `${resp.status}`;
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

export interface DocumentInfoData {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  chunk_count: number;
  status: string;
  error?: string | null;
  created_at: string;
}
export interface ConversationInfoData {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}
export interface DecisionData {
  name: string;
  label: string;
  kind: string;
  question: string;
  answer: unknown;
  probabilities?: Record<string, number> | null;
  confidence?: number | null;
  latency_ms: number;
}
export interface LiteChunkData {
  rank?: number;
  chunk_id: string;
  filename: string;
  similarity: number;
  jev_score?: number | null;
  snippet: string;
}
export interface CitationData {
  index: number;
  chunk_id: string;
  doc_id: string;
  filename: string;
  similarity: number;
  rerank_score?: number | null;
  snippet: string;
}
export interface TraceData {
  pipeline?: string;
  timings?: Record<string, number>;
  decisions?: DecisionData[];
  retrieved?: LiteChunkData[];
  citations?: CitationData[];
  context_sufficiency?: number | null;
  verification?: number | null;
}
export interface MessageData {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  mode?: string | null;
  content: string;
  model?: string | null;
  latency_ms?: number | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  cost_usd?: number | null;
  trace?: TraceData | null;
  created_at: string;
}
export interface SystemStatusData {
  status: string;
  version: string;
  dashscope: { ok: boolean; models?: string[]; error?: string; base_url?: string };
  jev: { ok: boolean; model?: string; backend?: string; error?: string; quant?: string; load_seconds?: number };
  embeddings: { ok: boolean; model?: string; error?: string };
  vector_store: { ok: boolean; chunks: number };
  documents: { total: number; ready: number; conversations: number };
  config: {
    llm_model_default: string;
    llm_model_reasoning: string;
    embed_model: string;
    top_k_retrieve: number;
    top_k_use: number;
  };
}

export const api = {
  documents: () => fetchJSON<{ documents: DocumentInfoData[] }>("/documents"),
  conversations: () => fetchJSON<{ conversations: ConversationInfoData[] }>("/conversations"),
  conversationMessages: (id: string) =>
    fetchJSON<{ messages: MessageData[] }>(`/conversations/${id}/messages`),
  systemStatus: () => fetchJSON<SystemStatusData>("/system/status"),
  health: () => fetchJSON<{ status: string }>("/system/health"),
};

/** Ask the Next.js server to (re)spawn the Python backend if it is down. */
export async function ensureBackend(): Promise<boolean> {
  try {
    const res = await fetch("/api/ensure-backend", { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

export interface ChatRequestBody {
  message: string;
  conversation_id?: string | null;
  mode: "traditional" | "hybrid";
}

/** POST /api/chat as a streaming SSE reader. Calls onEvent for every event frame. */
export async function streamChat(
  body: ChatRequestBody,
  onEvent: (evt: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch("/backend-api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    let detail = `HTTP ${resp.status}`;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
      if (dataLine) {
        try {
          onEvent(JSON.parse(dataLine.slice(6)));
        } catch {
          /* skip malformed frame */
        }
      }
    }
  }
}

export async function uploadDocuments(files: File[]): Promise<DocumentInfoData[]> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const resp = await fetch("/backend-api/documents", { method: "POST", body: form });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const body = (await resp.json()) as { documents: DocumentInfoData[] };
  return body.documents;
}

export async function deleteDocument(id: string): Promise<void> {
  await fetchJSON(`/documents/${id}`, { method: "DELETE" });
}

export async function deleteConversation(id: string): Promise<void> {
  await fetchJSON(`/conversations/${id}`, { method: "DELETE" });
}
