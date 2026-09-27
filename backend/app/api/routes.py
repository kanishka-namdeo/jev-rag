"""API routes: chat (SSE), documents, conversations, system status."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.db import Conversation, Document, Message, db_session, init_db
from app.rag.ingestion import SUPPORTED_EXTENSIONS, IngestionError, Ingestor
from app.rag.pipelines import ChatService
from app.schemas import ChatRequest, ConversationOut, DocumentOut, MessageOut

logger = logging.getLogger("jevrag.api")

router = APIRouter(prefix="/api")

# Basic CSRF-ish safety for filenames, and a hard cap per upload
_MAX_FILE_BYTES = 25 * 1024 * 1024
_MAX_FILES_PER_REQUEST = 10


def _svc(request: Request) -> ChatService:
    return request.app.state.chat_service


def _ing(request: Request) -> Ingestor:
    return request.app.state.ingestor


def _iso(dt) -> str:
    return dt.isoformat() if dt else ""


def _doc_out(d: Document) -> dict:
    return DocumentOut(id=d.id, filename=d.filename, file_type=d.file_type, file_size=d.file_size,
                       chunk_count=d.chunk_count, status=d.status, error=d.error,
                       created_at=_iso(d.created_at)).model_dump()


# ================================================================ chat (SSE)
@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    service = _svc(request)
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def producer():
        try:
            async for evt in service.run(req):
                await queue.put(evt)
        except Exception as e:  # noqa: BLE001 — stream must end with an error frame, never crash
            logger.exception("chat producer failed")
            await queue.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            await queue.put(None)

    prod_task = asyncio.create_task(producer())

    async def heartbeat():
        """Keeps the SSE connection warm through long local-model calls."""
        while not prod_task.done():
            await asyncio.sleep(10)
            if prod_task.done():
                break
            if queue.empty():
                await queue.put({"type": "ping"})

    hb_task = asyncio.create_task(heartbeat())

    async def gen():
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        finally:
            hb_task.cancel()
            prod_task.cancel()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ================================================================ documents
def _safe_upload_path(uploads_dir: Path, original_name: str) -> Path:
    ext = Path(original_name).suffix.lower()
    if ext and ext not in SUPPORTED_EXTENSIONS:
        raise IngestionError(
            f"unsupported file type '{ext}' — supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    return uploads_dir / f"{uuid.uuid4().hex}{ext}"


def _ingest_one(path: Path, filename: str, size: int, ingestor: Ingestor) -> dict:
    """Runs in a worker thread with its own DB session."""
    with db_session() as session:
        doc = ingestor.ingest_file(session, path, filename=filename, file_size=size)
        return _doc_out(doc)


@router.post("/documents")
async def upload_documents(request: Request, files: list[UploadFile] = File(...)):
    if len(files) > _MAX_FILES_PER_REQUEST:
        raise HTTPException(400, f"too many files (max {_MAX_FILES_PER_REQUEST} per request)")
    ingestor = _ing(request)
    results: list[dict] = []
    for f in files:
        data = await f.read()
        if len(data) > _MAX_FILE_BYTES:
            results.append({"filename": f.filename, "status": "error",
                            "error": "file exceeds 25 MB limit"})
            continue
        if not data:
            results.append({"filename": f.filename, "status": "error", "error": "empty file"})
            continue
        try:
            path = _safe_upload_path(request.app.state.settings.uploads_dir, f.filename or "file")
            path.write_bytes(data)
            doc = await asyncio.to_thread(_ingest_one, path, f.filename or path.name,
                                          len(data), ingestor)
            results.append(doc)
        except IngestionError as e:
            results.append({"filename": f.filename, "status": "error", "error": str(e)})
    return {"documents": results}


@router.get("/documents")
async def list_documents():
    with db_session() as session:
        docs = session.execute(select(Document).order_by(Document.created_at.desc())).scalars().all()
        return {"documents": [_doc_out(d) for d in docs]}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, request: Request):
    ingestor = _ing(request)

    def _delete():
        with db_session() as session:
            return ingestor.delete_document(session, doc_id)

    ok = await asyncio.to_thread(_delete)
    if not ok:
        raise HTTPException(404, "document not found")
    return {"deleted": doc_id}


# ================================================================ conversations
@router.get("/conversations")
async def list_conversations():
    with db_session() as session:
        rows = session.execute(
            select(Conversation, func.count(Message.id))
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .group_by(Conversation.id)
            .order_by(Conversation.updated_at.desc())
            .limit(100)
        ).all()
        return {"conversations": [
            ConversationOut(id=c.id, title=c.title, created_at=_iso(c.created_at),
                            updated_at=_iso(c.updated_at), message_count=n).model_dump()
            for c, n in rows
        ]}


@router.get("/conversations/{conv_id}/messages")
async def conversation_messages(conv_id: str):
    with db_session() as session:
        conv = session.get(Conversation, conv_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        msgs = session.execute(
            select(Message).where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
        ).scalars().all()
        return {"messages": [
            MessageOut(id=m.id, conversation_id=m.conversation_id, role=m.role, mode=m.mode,
                       content=m.content, model=m.model, latency_ms=m.latency_ms,
                       prompt_tokens=m.prompt_tokens, completion_tokens=m.completion_tokens,
                       cost_usd=m.cost_usd, trace=m.trace, created_at=_iso(m.created_at)).model_dump()
            for m in msgs
        ]}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    def _delete():
        with db_session() as session:
            conv = session.get(Conversation, conv_id)
            if conv is None:
                return False
            for m in session.execute(select(Message).where(Message.conversation_id == conv_id)).scalars():
                session.delete(m)
            session.delete(conv)
            session.commit()
            return True
    ok = await asyncio.to_thread(_delete)
    if not ok:
        raise HTTPException(404, "conversation not found")
    return {"deleted": conv_id}


# ================================================================ system
@router.get("/system/health")
async def health():
    return {"status": "ok", "service": "jev-rag-backend"}


@router.get("/system/status")
async def system_status(request: Request):
    state = request.app.state
    llm_health = await asyncio.to_thread(state.llm.health)
    with db_session() as session:
        doc_count = session.execute(select(func.count(Document.id))).scalar() or 0
        ready_count = session.execute(
            select(func.count(Document.id)).where(Document.status == "ready")).scalar() or 0
        conv_count = session.execute(select(func.count(Conversation.id))).scalar() or 0
    return {
        "status": "ok",
        "version": request.app.state.version,
        "dashscope": llm_health,
        "jev": state.jev.info(),
        "embeddings": state.embedder.info(),
        "vector_store": state.store.info(),
        "documents": {"total": doc_count, "ready": ready_count, "conversations": conv_count},
        "config": {
            "llm_model_default": state.settings.llm_model_default,
            "llm_model_reasoning": state.settings.llm_model_reasoning,
            "embed_model": state.settings.embed_model,
            "top_k_retrieve": state.settings.top_k_retrieve,
            "top_k_use": state.settings.top_k_use,
        },
    }
