"use client";

/** Central client state: chat (with SSE streaming), documents, conversations, status. */

import { toast } from "sonner";
import { create } from "zustand";

import {
  api,
  deleteConversation as apiDeleteConv,
  deleteDocument as apiDeleteDoc,
  ensureBackend,
  streamChat,
  uploadDocuments,
  type CitationData,
  type ConversationInfoData,
  type DecisionData,
  type DocumentInfoData,
  type LiteChunkData,
  type SystemStatusData,
} from "@/lib/jevrag/api";
import type { ChatMessage, Mode, PipelineMode } from "@/lib/jevrag/types";

let counter = 0;
const localId = () => `local-${Date.now()}-${counter++}`;

interface JevRagState {
  mode: Mode;
  conversationId: string | null;
  messages: ChatMessage[];
  streaming: boolean;
  documents: DocumentInfoData[];
  conversations: ConversationInfoData[];
  status: SystemStatusData | null;
  uploading: boolean;
  traceOpen: boolean;
  traceMessageId: string | null;

  setMode: (mode: Mode) => void;
  init: () => Promise<void>;
  refreshDocuments: () => Promise<void>;
  refreshConversations: () => Promise<void>;
  refreshStatus: () => Promise<void>;

  send: (text: string) => Promise<void>;
  newChat: () => void;
  loadConversation: (id: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;

  uploadFiles: (files: File[]) => Promise<void>;
  deleteDocument: (id: string) => Promise<void>;

  openTrace: (messageId: string) => void;
  closeTrace: () => void;
}

function applyEvent(msg: ChatMessage, evt: Record<string, unknown>): ChatMessage {
  switch (evt.type) {
    case "status":
      return { ...msg, stage: String(evt.detail ?? evt.stage ?? "") };
    case "retrieval":
      return { ...msg, retrieved: (evt.retrieved as LiteChunkData[]) ?? msg.retrieved };
    case "decision":
      return { ...msg, decisions: [...(msg.decisions ?? []), evt.decision as DecisionData] };
    case "routing":
      return {
        ...msg,
        routing: {
          model: String(evt.model ?? ""),
          probabilities: (evt.probabilities as Record<string, number>) ?? {},
          confidence: (evt.confidence as number | undefined) ?? undefined,
        },
      };
    case "sources":
      return { ...msg, sources: (evt.citations as CitationData[]) ?? [] };
    case "llm_start":
      return {
        ...msg,
        model: String(evt.model ?? msg.model ?? ""),
        stage: "answering…",
        contextSufficiency:
          (evt.context_sufficiency as number | undefined) ?? msg.contextSufficiency ?? null,
      };
    case "delta":
      return { ...msg, content: msg.content + String(evt.content ?? "") };
    case "done":
      return {
        ...msg,
        pending: false,
        stage: undefined,
        model: String(evt.model ?? msg.model ?? ""),
        latencyMs: evt.latency_ms as number | undefined,
        promptTokens: ((evt.usage as Record<string, number> | undefined) ?? {}).prompt_tokens,
        completionTokens: ((evt.usage as Record<string, number> | undefined) ?? {}).completion_tokens,
        costUsd: (evt.cost_usd as number | null | undefined) ?? null,
        timings: (evt.timings as Record<string, number> | undefined) ?? msg.timings,
        verification: (evt.verification as number | null | undefined) ?? null,
        contextSufficiency:
          (evt.context_sufficiency as number | null | undefined) ?? msg.contextSufficiency ?? null,
        content: (evt.content as string | undefined) ?? msg.content,
      };
    case "error":
      return { ...msg, pending: false, stage: undefined, error: String(evt.message ?? "error") };
    default:
      return msg;
  }
}

function placeholder(mode: PipelineMode, pairKey?: string): ChatMessage {
  return {
    id: localId(),
    role: "assistant",
    content: "",
    mode,
    pending: true,
    stage: "connecting…",
    decisions: [],
    pairKey,
  };
}

export const useJevRag = create<JevRagState>((set, get) => ({
  mode: "traditional",
  conversationId: null,
  messages: [],
  streaming: false,
  documents: [],
  conversations: [],
  status: null,
  uploading: false,
  traceOpen: false,
  traceMessageId: null,

  setMode: (mode) => set({ mode }),

  init: async () => {
    // Self-heal: make sure the Python backend is up before any API calls.
    await ensureBackend();
    await Promise.all([
      get().refreshDocuments(),
      get().refreshConversations(),
      get().refreshStatus(),
    ]);
  },

  refreshDocuments: async () => {
    try {
      const { documents } = await api.documents();
      set({ documents });
    } catch (e) {
      console.warn("documents refresh failed", e);
    }
  },

  refreshConversations: async () => {
    try {
      const { conversations } = await api.conversations();
      set({ conversations });
    } catch (e) {
      console.warn("conversations refresh failed", e);
    }
  },

  refreshStatus: async () => {
    try {
      set({ status: await api.systemStatus() });
    } catch (e) {
      console.warn("status refresh failed", e);
    }
  },

  send: async (text) => {
    const trimmed = text.trim();
    const { mode, conversationId, streaming } = get();
    if (!trimmed || streaming) return;

    const userMsg: ChatMessage = { id: localId(), role: "user", content: trimmed };
    const runOne = async (pipeMode: PipelineMode, msgId: string) => {
      const update = (fn: (m: ChatMessage) => ChatMessage) =>
        set((s) => ({ messages: s.messages.map((m) => (m.id === msgId ? fn(m) : m)) }));
      const runStream = () =>
        streamChat(
          { message: trimmed, conversation_id: conversationId, mode: pipeMode },
          (evt) => {
            if (evt.type === "meta" && evt.conversation_id) {
              const cid = String(evt.conversation_id);
              if (get().conversationId !== cid) set({ conversationId: cid });
            }
            update((m) => applyEvent(m, evt));
          },
        );
      try {
        await runStream();
      } catch (firstErr) {
        // Self-heal once: the backend may have been reaped between calls.
        update((m) => ({ ...m, stage: "backend waking up… retrying" }));
        const ok = await ensureBackend();
        if (ok) {
          try {
            await runStream();
            return;
          } catch (secondErr) {
            update((m) => ({ ...m, pending: false, stage: undefined, error: String(secondErr) }));
            return;
          }
        }
        update((m) => ({ ...m, pending: false, stage: undefined, error: String(firstErr) }));
      }
    };

    if (mode === "compare") {
      const pairKey = localId();
      const trad = placeholder("traditional", pairKey);
      const hyb = placeholder("hybrid", pairKey);
      set((s) => ({
        messages: [...s.messages, userMsg, trad, hyb],
        streaming: true,
        traceOpen: true,
        traceMessageId: hyb.id,
      }));
      await Promise.all([runOne("traditional", trad.id), runOne("hybrid", hyb.id)]);
    } else {
      const asst = placeholder(mode);
      set((s) => ({ messages: [...s.messages, userMsg, asst], streaming: true }));
      await runOne(mode, asst.id);
    }
    set({ streaming: false });
    void get().refreshConversations();
  },

  newChat: () => set({ conversationId: null, messages: [], traceMessageId: null, traceOpen: false }),

  loadConversation: async (id) => {
    try {
      const { messages } = await api.conversationMessages(id);
      set({
        conversationId: id,
        traceMessageId: null,
        traceOpen: false,
        messages: messages.map((m): ChatMessage => ({
          id: m.id,
          role: m.role,
          content: m.content,
          mode: (m.mode as PipelineMode | null) ?? undefined,
          model: m.model ?? undefined,
          latencyMs: m.latency_ms ?? undefined,
          promptTokens: m.prompt_tokens ?? undefined,
          completionTokens: m.completion_tokens ?? undefined,
          costUsd: m.cost_usd ?? null,
          sources: m.trace?.citations ?? undefined,
          retrieved: m.trace?.retrieved ?? undefined,
          decisions: (m.trace?.decisions as DecisionData[] | undefined) ?? undefined,
          verification: m.trace?.verification ?? null,
          contextSufficiency: m.trace?.context_sufficiency ?? null,
          timings: m.trace?.timings ?? undefined,
          createdAt: m.created_at,
        })),
      });
    } catch (e) {
      toast.error("Failed to load conversation", { description: String(e) });
    }
  },

  deleteConversation: async (id) => {
    try {
      await apiDeleteConv(id);
      if (get().conversationId === id) get().newChat();
      await get().refreshConversations();
      toast.success("Conversation deleted");
    } catch (e) {
      toast.error("Delete failed", { description: String(e) });
    }
  },

  uploadFiles: async (files) => {
    if (!files.length) return;
    set({ uploading: true });
    try {
      const docs = await uploadDocuments(files);
      await get().refreshDocuments();
      const failed = docs.filter((d) => d.status === "error");
      if (failed.length) {
        toast.error(`${failed.length}/${docs.length} file(s) failed to index`, {
          description: failed[0].error ?? "unknown error",
        });
      } else {
        toast.success(`Indexed ${docs.length} file(s)`);
      }
    } catch (e) {
      toast.error("Upload failed", { description: String(e) });
    } finally {
      set({ uploading: false });
    }
  },

  deleteDocument: async (id) => {
    try {
      await apiDeleteDoc(id);
      await get().refreshDocuments();
      toast.success("Document removed");
    } catch (e) {
      toast.error("Delete failed", { description: String(e) });
    }
  },

  openTrace: (messageId) => set({ traceOpen: true, traceMessageId: messageId }),
  closeTrace: () => set({ traceOpen: false }),
}));
