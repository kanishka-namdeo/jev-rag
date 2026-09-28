"""FastAPI application entrypoint.

Run: cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

import app  # noqa: F401  (ensures package init)
from app import __version__
from app.api.bench_routes import router as bench_router
from app.api.routes import router
from app.bench.judge import BenchJudge
from app.bench.runner import BenchRunner
from app.config import get_settings
from app.db import init_db
from app.llm.dashscope import DashscopeLLM
from app.llm.jev_engine import JevEngine
from app.rag.ingestion import Ingestor
from app.rag.pipelines import ChatService
from app.rag.retriever import Embedder, VectorStore

logger = logging.getLogger("jevrag.main")


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    settings = get_settings()
    t0 = time.perf_counter()
    init_db()

    embedder = Embedder(settings)
    store = VectorStore(settings)
    jev = JevEngine(settings)
    llm = DashscopeLLM(settings)

    if not settings.lazy_models:
        logger.info("loading local models (eager warm-up)…")
        store.load()
        embedder.load()
        jev.load()
        logger.info("local models ready in %.1fs", time.perf_counter() - t0)
    else:
        store.load()

    fastapi_app.state.settings = settings
    fastapi_app.state.version = __version__
    fastapi_app.state.embedder = embedder
    fastapi_app.state.store = store
    fastapi_app.state.jev = jev
    fastapi_app.state.llm = llm
    fastapi_app.state.ingestor = Ingestor(settings, embedder, store)
    fastapi_app.state.chat_service = ChatService(settings, llm, jev, embedder, store)
    fastapi_app.state.bench_judge = BenchJudge(settings)
    fastapi_app.state.bench_runner = BenchRunner(
        settings, llm, jev, embedder, store, fastapi_app.state.ingestor,
        fastapi_app.state.bench_judge)
    _reap_orphaned_bench_runs()
    logger.info("backend up (v%s) in %.1fs — lazy_models=%s", __version__,
                time.perf_counter() - t0, settings.lazy_models)
    yield
    logger.info("backend shutting down")


def _reap_orphaned_bench_runs() -> None:
    """Mark runs stuck in a live status as failed — their asyncio tasks died
    with the previous process (restart, crash, OOM kill)."""
    from app.db import BenchRun, db_session

    try:
        with db_session() as session:
            orphans = session.execute(
                select(BenchRun).where(
                    BenchRun.status.in_(("queued", "running", "cancelling")))
            ).scalars().all()
            for run in orphans:
                run.status = "failed"
                run.error = (f"run orphaned by backend restart (was {run.status} at "
                             f"{run.progress_done}/{run.progress_total})")
                run.finished_at = datetime.now(timezone.utc)
            if orphans:
                session.commit()
                logger.warning("reaped %d orphaned bench run(s)", len(orphans))
    except Exception as e:  # noqa: BLE001 — bookkeeping must never block startup
        logger.warning("bench run reaping failed: %s", e)


def create_app() -> FastAPI:
    application = FastAPI(
        title="Jev-RAG backend",
        description="Hybrid RAG: local Jev-style System One decisions + cloud LLM System Two",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # local demo: gateway-proxied, no cookies/auth
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # /api/* is for direct access; /backend-api/* is what the Next.js server
    # rewrites to (works both through the gateway and on localhost:3000).
    application.include_router(router, prefix="/api")
    application.include_router(router, prefix="/backend-api")
    application.include_router(bench_router, prefix="/api")
    application.include_router(bench_router, prefix="/backend-api")
    return application


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, log_level="info")
