"""Local embeddings (fastembed/ONNX, multilingual-e5-small) + ChromaDB vector store
+ v3 hybrid retrieval (BM25 ‖ dense, RRF fusion).

fastembed applies the e5 "query:"/"passage:" prefixes automatically.
ChromaDB runs embedded+persistent (no server), cosine space.

v3 (docs/rag-upgrade-2026.md §3.1): :class:`HybridSearch` runs BM25 and dense
retrieval in parallel and fuses them with reciprocal-rank fusion — the 2026
production default. BM25 rescues exact entity/lexical lookups that dense
embeddings rank poorly; RRF needs no comparable score scales. The BM25 index
is rebuilt lazily from Chroma's stored chunk texts whenever the vector store's
in-memory revision changes (any upsert/delete bumps it), so there is no
persistence format and no drift: Chroma remains the single source of truth.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import Settings
from app.rag.lexical import LexicalIndex

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
    rrf_score: float | None = field(default=None)  # fused RRF rank score (v3 hybrid mode)

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id, "doc_id": self.doc_id, "filename": self.filename,
            "chunk_index": self.chunk_index, "similarity": round(self.similarity, 4),
            "jev_score": round(self.jev_score, 4) if self.jev_score is not None else None,
            "rrf_score": round(self.rrf_score, 5) if self.rrf_score is not None else None,
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
        vec = next(iter(self._model.embed([text], batch_size=1)))
        # tolist(): pure python floats — chromadb 1.5.9's validator rejects
        # np.float32 scalars nested in plain lists (bge models return them)
        return [float(x) for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._ensure()
        out: list[list[float]] = []
        for v in self._model.embed(texts, batch_size=16):
            # tolist(): pure python floats — chromadb 1.5.9's validator rejects
            # np.float32 scalars nested in plain lists (bge models return them)
            out.append([float(x) for x in v])
        return out

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

    def __init__(self, settings: Settings, collection_name: str | None = None):
        self.settings = settings
        self._client = None
        self._collection = None
        # Collection name is overridable per instance: the hermetic test suite
        # creates many stores in ONE process, and Chroma's embedded Rust core
        # keys segment state by collection name — a fixed name would leak data
        # across stores even with different paths (observed in test runs).
        self.collection_name = collection_name or self.COLLECTION
        # In-memory mutation counter: every upsert/delete bumps it. HybridSearch
        # rebuilds its BM25 index when this changes (and both reset together on
        # process restart — Chroma on disk is the only persisted state).
        self.revision: int = 0

    def load(self) -> bool:
        if self._collection is not None:
            return True
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.settings.chroma_dir))
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name, metadata={"hnsw:space": "cosine"}
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
        self.revision += 1
        return len(ids)

    def all_chunks(self, doc_ids: list[str] | None = None) -> list[tuple[str, str]]:
        """(chunk_id, text) for the whole collection (or a doc subset) — the
        corpus source for BM25 index builds. Scenario isolation: passing
        doc_ids keeps lexical retrieval inside the benchmark corpus."""
        self._ensure()
        if doc_ids is None:
            res = self._collection.get(include=["documents"])
        else:
            res = self._collection.get(where={"doc_id": {"$in": list(doc_ids)}},
                                       include=["documents"])
        return list(zip(res["ids"], res["documents"]))

    def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[RetrievedChunk]:
        """Fetch specific chunks (documents + metadatas) by id — used to
        materialize BM25-only hits after RRF fusion."""
        self._ensure()
        if not chunk_ids:
            return []
        res = self._collection.get(ids=list(chunk_ids),
                                   include=["documents", "metadatas"])
        out: list[RetrievedChunk] = []
        for cid, doc, meta in zip(res.get("ids") or [], res.get("documents") or [],
                                  res.get("metadatas") or []):
            meta = meta or {}
            out.append(RetrievedChunk(
                chunk_id=cid, text=doc or "", doc_id=meta.get("doc_id", ""),
                filename=meta.get("filename", ""),
                chunk_index=int(meta.get("chunk_index", 0)), similarity=0.0))
        return out

    def query(self, embedding: list[float], k: int,
              doc_ids: list[str] | None = None) -> list[RetrievedChunk]:
        """k nearest chunks (cosine). doc_ids restricts the search to a document
        subset (benchmark scenario isolation)."""
        self._ensure()
        where = {"doc_id": {"$in": list(doc_ids)}} if doc_ids is not None else None
        res = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(k, max(self.count(), 1)),
            where=where,
        )
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
        self.revision += 1

    def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()

    def info(self) -> dict:
        return {"ok": self.available, "path": str(self.settings.chroma_dir), "chunks": self.count()}


class HybridSearch:
    """BM25 ‖ dense retrieval fused with RRF — the v3 default retriever.

    Wraps the existing Embedder + VectorStore; the BM25 (lexical) index is
    rebuilt lazily from the vector store's stored chunk texts whenever the
    store's in-memory revision changes, scoped to doc_ids when a benchmark
    scenario needs isolation. Returns RetrievedChunk objects in fused order;
    `similarity` keeps the dense cosine similarity when the chunk appeared in
    the dense ranking (0.0 for lexical-only hits — RRF ranks, not scores, are
    the ordering signal; the cross-encoder reranker re-scores the pool later).
    """

    def __init__(self, settings: Settings, embedder: Embedder, store: VectorStore):
        self.settings = settings
        self.embedder = embedder
        self.store = store
        self._index = LexicalIndex(k1=settings.bm25_k1, b=settings.bm25_b)
        # (store_revision, doc_ids key) the current BM25 index was built for
        self._built_for: tuple[int, str] | None = None
        self.last_build_ms: float = 0.0

    def _lexical_ready(self, doc_ids: list[str] | None) -> bool:
        key = ",".join(sorted(doc_ids)) if doc_ids else "*"
        return self._built_for == (getattr(self.store, "revision", 0), key)

    def _rebuild(self, doc_ids: list[str] | None) -> None:
        import time as _t
        t0 = _t.perf_counter()
        corpus = self.store.all_chunks(doc_ids)
        self._index.build(corpus)
        key = ",".join(sorted(doc_ids)) if doc_ids else "*"
        self._built_for = (getattr(self.store, "revision", 0), key)
        self.last_build_ms = round((_t.perf_counter() - t0) * 1000, 1)
        logger.info("lexical index rebuilt: %d chunks in %.0fms (scope=%s)",
                    self._index.doc_count, self.last_build_ms,
                    f"{len(doc_ids)} docs" if doc_ids else "all")

    def retrieve(self, query: str, k: int,
                 doc_ids: list[str] | None = None) -> list[RetrievedChunk]:
        """Top-k chunks by RRF over BM25 + dense rankings (k from EACH source)."""
        if self.settings.retrieval_mode != "hybrid_rrf":
            # pre-v3 behaviour: dense-only (fallback arm for the testbench)
            embedding = self.embedder.embed_query(query)
            return self.store.query(embedding, k, doc_ids=doc_ids)

        if not self._lexical_ready(doc_ids):
            self._rebuild(doc_ids)

        embedding = self.embedder.embed_query(query)
        dense = self.store.query(embedding, k, doc_ids=doc_ids)
        lexical = self._index.query(query, top_n=k) if self._index.doc_count else []

        # fused RRF score per id: sum of 1/(rrf_k + rank) over both rankings
        fused: dict[str, float] = {}
        for ranking in ([c.chunk_id for c in dense], [cid for cid, _ in lexical]):
            for rank, cid in enumerate(ranking, start=1):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (self.settings.rrf_k + rank)
        fused_ids = sorted(fused, key=lambda cid: (-fused[cid], cid))[:k]

        dense_by_id = {c.chunk_id: c for c in dense}
        missing = [cid for cid in fused_ids if cid not in dense_by_id]
        lexical_by_id = self._chunks_by_ids(missing) if missing else {}
        out: list[RetrievedChunk] = []
        for cid in fused_ids:
            chunk = dense_by_id.get(cid) or lexical_by_id.get(cid)
            if chunk is not None:
                chunk.rrf_score = fused[cid]
                out.append(chunk)
        return out

    def _chunks_by_ids(self, chunk_ids: list[str]) -> dict[str, RetrievedChunk]:
        """Materialize RetrievedChunks for BM25-only hits in ONE batched fetch
        (metadatas live in the vector store; the BM25 index stores texts).
        similarity 0.0 marks a lexical-only hit (dense cosine not defined);
        rerank scores (not this field) drive final ordering in v3."""
        if not chunk_ids:
            return {}
        return {c.chunk_id: c for c in self.store.get_chunks_by_ids(chunk_ids)}

    def info(self) -> dict:
        return {
            "mode": self.settings.retrieval_mode,
            "bm25_chunks": self._index.doc_count,
            "bm25_built_for": self._built_for is not None,
            "last_build_ms": self.last_build_ms,
        }
