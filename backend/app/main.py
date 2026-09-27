"""FastAPI application entrypoint.

Run: cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app  # noqa: F401  (ensures package init)
from app import __version__
from app.api.routes import router
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
    logger.info("backend up (v%s) in %.1fs — lazy_models=%s", __version__,
                time.perf_counter() - t0, settings.lazy_models)
    yield
    logger.info("backend shutting down")


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
    application.include_router(router)
    return application


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, log_level="info")
