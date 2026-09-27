"""Local embeddings (fastembed/ONNX, multilingual-e5-small) + ChromaDB vector store.

fastembed applies the e5 "query:"/"passage:" prefixes automatically.
ChromaDB runs embedded+persistent (no server), cosine space.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import Settings

logger = logging.getLogger("jevrag.retriever")


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    doc_id: str
    filename: str
    chunk_index: int
    similarity: float
    jev_score: float | None = field(default=None)

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id, "doc_id": self.doc_id, "filename": self.filename,
            "chunk_index": self.chunk_index, "similarity": round(self.similarity, 4),
            "jev_score": round(self.jev_score, 4) if self.jev_score is not None else None,
            "text": self.text,
        }


class Embedder:
    """Thread-safe lazy wrapper around fastembed TextEmbedding."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._dim: int | None = None
        self._error: str | None = None

    def load(self) -> bool:
        if self._model is not None or self._error is not None:
            return self._model is not None
        try:
            from fastembed import TextEmbedding

            logger.info("loading embedding model %s (cache=%s)",
                        self.settings.embed_model, self.settings.fastembed_cache_dir)
            self._model = TextEmbedding(
                model_name=self.settings.embed_model,
                cache_dir=str(self.settings.fastembed_cache_dir),
            )
            logger.info("embedding model ready")
            return True
        except Exception as e:  # noqa: BLE001
            self._error = f"{type(e).__name__}: {e}"
            logger.error("embedding model failed to load: %s", self._error)
            return False

    @property
    def available(self) -> bool:
        return self._model is not None

    def _ensure(self):
        if self._model is None:
            if not self.load():
                raise RuntimeError(f"embedding model unavailable: {self._error}")

    def embed_query(self, text: str) -> list[float]:
        self._ensure()
        return list(next(iter(self._model.embed([text], batch_size=1))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._ensure()
        return [list(v) for v in self._model.embed(texts, batch_size=16)]

    def info(self) -> dict:
        return {
            "ok": self.available,
            "model": self.settings.embed_model,
            "backend": "onnx (fastembed, CPU)",
            **({"error": self._error} if self._error else {}),
        }


class VectorStore:
    """ChromaDB embedded persistent store."""

    COLLECTION = "jevrag_chunks"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        self._collection = None

    def load(self) -> bool:
        if self._collection is not None:
            return True
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.settings.chroma_dir))
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION, metadata={"hnsw:space": "cosine"}
            )
            logger.info("chroma ready at %s (%d chunks)", self.settings.chroma_dir, self._collection.count())
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("chroma failed to init: %s", e)
            return False

    @property
    def available(self) -> bool:
        return self._collection is not None

    def _ensure(self):
        if self._collection is None:
            if not self.load():
                raise RuntimeError("vector store unavailable")

    def add_chunks(self, doc_id: str, filename: str, texts: list[str],
                   embeddings: list[list[float]]) -> int:
        self._ensure()
        ids = [f"{doc_id}:{i}" for i in range(len(texts))]
        metadatas = [{"doc_id": doc_id, "filename": filename, "chunk_index": i}
                     for i in range(len(texts))]
        # upsert makes re-indexing the same document idempotent
        self._collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        return len(ids)

    def query(self, embedding: list[float], k: int) -> list[RetrievedChunk]:
        self._ensure()
        res = self._collection.query(query_embeddings=[embedding], n_results=min(k, max(self.count(), 1)))
        chunks: list[RetrievedChunk] = []
        if not res.get("ids") or not res["ids"][0]:
            return chunks
        for i, cid in enumerate(res["ids"][0]):
            meta = res["metadatas"][0][i] or {}
            doc = res["documents"][0][i] or ""
            dist = float(res["distances"][0][i]) if res.get("distances") else 0.0
            chunks.append(RetrievedChunk(
                chunk_id=cid, text=doc, doc_id=meta.get("doc_id", ""),
                filename=meta.get("filename", ""), chunk_index=int(meta.get("chunk_index", 0)),
                similarity=1.0 - dist,  # cosine distance -> similarity
            ))
        return chunks

    def delete_document(self, doc_id: str) -> None:
        self._ensure()
        self._collection.delete(where={"doc_id": doc_id})

    def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()

    def info(self) -> dict:
        return {"ok": self.available, "path": str(self.settings.chroma_dir), "chunks": self.count()}
