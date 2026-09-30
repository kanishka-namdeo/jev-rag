"""SQLite persistence (documents registry, conversations, messages + traces) via SQLAlchemy."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(32), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="processing")  # processing|ready|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(256), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))               # user | assistant
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)  # traditional | hybrid
    content: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    trace: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BenchRun(Base):
    """One benchmark execution over a set of scenarios (both pipelines)."""
    __tablename__ = "bench_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(256), default="benchmark run")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    # queued | running | cancelling | cancelled | completed | failed
    scenario_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    judge_model: Mapped[str] = mapped_column(String(64), default="")
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_stage: Mapped[str] = mapped_column(String(256), default="")
    judge_selftest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BenchResult(Base):
    """One pipeline answer to one benchmark question (mode = traditional | hybrid)."""
    __tablename__ = "bench_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("bench_runs.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64))
    question_id: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(16))               # traditional | hybrid
    qtype: Mapped[str] = mapped_column(String(32), default="")
    answerable: Mapped[bool] = mapped_column(Boolean, default=True)
    reference: Mapped[str] = mapped_column(Text, default="")

    answer: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    retrieved_files: Mapped[list | None] = mapped_column(JSON, nullable=True)
    pre_rerank_files: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retrieval: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    naive_retrieval: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pairwise: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    sufficiency_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    verification_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    routed_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jev_decisions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            f"sqlite:///{settings.db_path}",
            # timeout -> SQLite busy handler: parallel workers own separate DBs, but
            # the status monitor reads a worker's DB while it is mid-transaction.
            # WAL stays off deliberately: backend/data* lives on /mnt/d (9p), where
            # WAL's shared-memory semantics are unreliable.
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def db_session() -> Session:
    """Context-manager style session factory."""
    get_engine()
    return _SessionLocal()


def init_db() -> None:
    Base.metadata.create_all(get_engine())
