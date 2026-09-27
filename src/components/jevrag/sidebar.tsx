"use client";

import { useRef, useState } from "react";
import {
  FileSpreadsheet,
  FileText,
  FileUp,
  Loader2,
  MessageSquare,
  Plus,
  Trash2,
  Upload,
} from "lucide-react";

import { formatBytes } from "@/components/jevrag/ui-bits";
import { useJevRag } from "@/lib/jevrag/store";
import { cn } from "@/lib/utils";

function FileIcon({ type }: { type: string }) {
  if (["xlsx", "csv"].includes(type)) return <FileSpreadsheet className="h-4 w-4" />;
  return <FileText className="h-4 w-4" />;
}

export function Sidebar() {
  const {
    conversations,
    documents,
    uploading,
    conversationId,
    uploadFiles,
    deleteDocument,
    loadConversation,
    deleteConversation,
    newChat,
    streaming,
  } = useJevRag();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const readyDocs = documents.filter((d) => d.status === "ready");

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <button
        type="button"
        onClick={newChat}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
      >
        <Plus className="h-4 w-4" /> New chat
      </button>

      {/* Documents */}
      <section className="flex min-h-0 flex-col">
        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <FileUp className="h-3.5 w-3.5" /> Knowledge base
        </h3>
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const files = Array.from(e.dataTransfer.files);
            if (files.length) void uploadFiles(files);
          }}
          className={cn(
            "mb-2 cursor-pointer rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground transition-colors hover:border-emerald-600/50 hover:bg-emerald-600/5",
            dragging && "border-emerald-600 bg-emerald-600/10",
          )}
        >
          {uploading ? (
            <span className="flex items-center justify-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" /> Parsing & indexing…
            </span>
          ) : (
            <span className="flex flex-col items-center gap-1">
              <Upload className="h-5 w-5" />
              Drop files or click to upload
              <span className="text-[10px]">PDF · DOCX · XLSX · TXT · MD · CSV · HTML</span>
            </span>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.xlsx,.txt,.md,.csv,.html,.htm,.json,.xml,.log"
          className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) void uploadFiles(files);
            e.target.value = "";
          }}
        />
        <ul className="max-h-64 space-y-1 overflow-y-auto pr-1">
          {documents.map((d) => (
            <li
              key={d.id}
              className="group flex items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-muted/60"
            >
              <FileIcon type={d.file_type} />
              <span className="min-w-0 flex-1 truncate" title={d.filename}>
                {d.filename}
              </span>
              {d.status === "ready" ? (
                <span className="shrink-0 font-mono text-[10px] text-muted-foreground" title={formatBytes(d.file_size)}>
                  {d.chunk_count} ch
                </span>
              ) : d.status === "error" ? (
                <span className="shrink-0 text-[10px] text-red-500" title={d.error ?? ""}>
                  error
                </span>
              ) : (
                <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
              )}
              <button
                type="button"
                onClick={() => void deleteDocument(d.id)}
                className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                title="Delete document"
                aria-label={`Delete ${d.filename}`}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </li>
          ))}
          {documents.length === 0 && (
            <li className="px-2 py-2 text-[11px] text-muted-foreground">
              No documents yet — upload some to ground the answers.
            </li>
          )}
        </ul>
      </section>

      {/* Conversations */}
      <section className="flex min-h-0 flex-1 flex-col">
        <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <MessageSquare className="h-3.5 w-3.5" /> History
        </h3>
        <ul className="flex-1 space-y-1 overflow-y-auto pr-1">
          {conversations.map((c) => (
            <li key={c.id} className="group">
              <div
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-muted/60",
                  conversationId === c.id && "bg-muted",
                )}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate text-left"
                  onClick={() => void loadConversation(c.id)}
                  disabled={streaming}
                >
                  {c.title}
                </button>
                <button
                  type="button"
                  onClick={() => void deleteConversation(c.id)}
                  className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                  title="Delete conversation"
                  aria-label={`Delete ${c.title}`}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </li>
          ))}
          {conversations.length === 0 && (
            <li className="px-2 py-2 text-[11px] text-muted-foreground">No conversations yet.</li>
          )}
        </ul>
      </section>

      <p className="shrink-0 text-[10px] leading-relaxed text-muted-foreground">
        {readyDocs.length} document(s) · answers are grounded in your uploaded files only.
      </p>
    </div>
  );
}
