"""Document ingestion: parse (markitdown) -> chunk (structure-aware, contextual
prefixes) -> embed -> index.

v3 chunking (docs/rag-upgrade-2026.md §3.1): chunks carry a contextual prefix
("doc title | section heading") — Anthropic's contextual-retrieval evidence
(top-20 retrieval failures 5.7% -> 3.7% with prefixes) at the cost of one
string concat at index time. Falls back to plain recursive splitting when
contextual_prefix is disabled.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Document, new_id
from app.rag.retriever import Embedder, VectorStore

logger = logging.getLogger("jevrag.ingestion")

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".html", ".htm", ".csv", ".json", ".xml", ".log"}


class IngestionError(ValueError):
    pass


class Ingestor:
    def __init__(self, settings: Settings, embedder: Embedder, store: VectorStore):
        self.settings = settings
        self.embedder = embedder
        self.store = store
        self._md = None

    def _markitdown(self):
        if self._md is None:
            from markitdown import MarkItDown

            self._md = MarkItDown()
        return self._md

    def ingest_file(self, session: Session, path: Path, filename: str | None = None,
                    file_type: str = "", file_size: int = 0) -> Document:
        filename = filename or path.name
        ext = Path(filename).suffix.lower() or Path(path).suffix.lower()
        if ext and ext not in SUPPORTED_EXTENSIONS:
            raise IngestionError(
                f"unsupported file type '{ext}' — supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

        doc = Document(id=new_id(), filename=filename, file_type=file_type or ext.lstrip("."),
                       file_size=file_size or path.stat().st_size, status="processing")
        session.add(doc)
        session.commit()
        try:
            text = self._extract_text(path)
            text = text.strip()
            if not text:
                raise IngestionError("no extractable text found in the file")
            chunks = self._split(text, filename)
            embeddings = self.embedder.embed_documents(chunks)
            self.store.add_chunks(doc.id, filename, chunks, embeddings)
            doc.chunk_count = len(chunks)
            doc.status = "ready"
            logger.info("ingested %s -> %d chunks", filename, len(chunks))
        except Exception as e:  # noqa: BLE001 — record per-document failure
            doc.status = "error"
            doc.error = f"{type(e).__name__}: {e}"
            logger.error("ingestion failed for %s: %s", filename, doc.error)
        session.commit()
        return doc

    def _extract_text(self, path: Path) -> str:
        result = self._markitdown().convert(str(path))
        return result.text_content or ""

    def _split(self, text: str, filename: str = "") -> list[str]:
        if self.settings.contextual_prefix:
            from app.rag.chunking import split_structure_aware

            specs = split_structure_aware(
                text, title=filename or Path("document").stem,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap)
            return [spec.text for spec in specs]

        from app.rag.chunking import split_plain

        return split_plain(text, chunk_size=self.settings.chunk_size,
                           overlap=self.settings.chunk_overlap)

    def delete_document(self, session: Session, doc_id: str) -> bool:
        doc = session.get(Document, doc_id)
        if doc is None:
            return False
        try:
            self.store.delete_document(doc_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("chroma delete failed for %s: %s", doc_id, e)
        session.delete(doc)
        session.commit()
        return True
