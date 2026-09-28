"""Pydantic schemas for API requests/responses and SSE events."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ChatMode = Literal["traditional", "hybrid"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    mode: ChatMode = "traditional"
    # Internal fields (not part of the public chat API surface — the benchmark
    # runner sets them when it drives the SAME ChatService orchestrator):
    # doc_ids restricts retrieval to a document subset (scenario isolation).
    doc_ids: list[str] | None = None
    # bench=True: no conversation persistence, done event carries the exact
    # context block used for generation, and errors PROPAGATE (the bench runner
    # needs real exceptions for its engine-retry logic) instead of becoming
    # SSE error events.
    bench: bool = False


class Citation(BaseModel):
    index: int
    chunk_id: str
    doc_id: str
    filename: str
    similarity: float                      # embedding similarity (both modes)
    rerank_score: float | None = None      # Jev calibrated P(relevant) — hybrid only


class JevDecision(BaseModel):
    """One System-One decision, as shown in the trace panel."""
    name: str                              # rerank | sufficiency | routing | verification
    label: str                             # human-readable title
    kind: str                              # noul | choice
    question: str                          # instructions/statement asked
    answer: Any                            # noul: float p; choice: option name
    probabilities: dict[str, float] | None = None
    confidence: float | None = None
    latency_ms: float
    usage: dict[str, int] | None = None


class DocumentOut(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    status: str
    error: str | None = None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    mode: str | None = None
    content: str
    model: str | None = None
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    trace: dict | None = None
    created_at: str


class SystemStatus(BaseModel):
    status: str
    version: str
    dashscope: dict[str, Any]
    jev: dict[str, Any]
    embeddings: dict[str, Any]
    vector_store: dict[str, Any]
    documents: dict[str, Any]
