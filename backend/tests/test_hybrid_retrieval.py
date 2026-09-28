"""Integration tests for the v3 hybrid retrieval stack (M3).

Real embedded Chroma (temp dir) + real BM25 index + deterministic fake
embedder — exercises RRF fusion, doc-scoped scenario isolation, lazy index
rebuilds on store revision changes, and the dense fallback mode.
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="jevrag-test-")
os.environ.setdefault("JEVRAG_LAZY_MODELS", "1")
os.environ.setdefault("JEVRAG_DATA_DIR", _TMP)
os.environ.setdefault("JEVRAG_DASHSCOPE_API_KEY", "test-key")

from app.config import Settings  # noqa: E402
from app.rag.retriever import Embedder, HybridSearch, VectorStore  # noqa: E402


class FakeEmbedder(Embedder):
    """Deterministic hashed embeddings — no model download, stable ranking:
    chunks sharing rare tokens with the query hash closer together."""

    def __init__(self):
        self.settings = None

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    @staticmethod
    def _embed(text: str) -> list[float]:
        import hashlib

        vec = [0.0] * 64
        for tok in text.lower().split():
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % 64] += 1.0
            vec[(h >> 8) % 64] += 0.5
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


def _settings(**over) -> Settings:
    base = dict(_env_file=None)
    base["chroma_dir"] = os.path.join(_TMP, "chroma-" + os.urandom(4).hex())
    base.update(over)
    return Settings(**base)


def _seed(store: VectorStore, docs: dict[str, list[str]]) -> None:
    emb = FakeEmbedder()
    for doc_id, texts in docs.items():
        store.add_chunks(doc_id, f"{doc_id}.md", texts, emb.embed_documents(texts))


# ------------------------------------------------------------------ fusion

def test_rrf_fusion_returns_both_dense_and_lexical_hits():
    s = _settings()
    store = VectorStore(s, collection_name="t_" + os.urandom(4).hex())
    store.load()
    _seed(store, {
        "d1": ["Zebra finch genome sequencing study"],          # lexical match: zebra
        "d2": ["Quantum tunneling effect in semiconductors"],   # lexical match: quantum
        "d3": ["Quarterly revenue growth analysis"],            # dense-ish filler
        "d4": ["Quantum computing error correction"],           # lexical: quantum
    })
    search = HybridSearch(s, FakeEmbedder(), store)
    hits = search.retrieve("quantum zebra", k=4)
    ids = [c.chunk_id for c in hits]
    # both lexically-matching docs must appear in the fused top-4
    assert "d1:0" in ids
    assert any(i.startswith("d2") or i.startswith("d4") for i in ids)
    # every returned chunk carries a fused rrf score
    assert all(c.rrf_score is not None and c.rrf_score > 0 for c in hits)


def test_lexical_only_hit_materialized_with_metadata():
    s = _settings()
    store = VectorStore(s, collection_name="t_" + os.urandom(4).hex())
    store.load()
    _seed(store, {
        "d1": ["Orphan lexical passage about xylophones"],
        "d2": ["Completely unrelated filler text here"],
        "d3": ["More filler content unrelated to music"],
        "d4": ["Yet more unrelated filler material"],
    })
    search = HybridSearch(s, FakeEmbedder(), store)
    hits = search.retrieve("xylophones", k=4)
    top = hits[0]
    # "xylophones" appears in exactly one doc: BM25 must rank it first even
    # though dense similarity may prefer something else
    assert top.chunk_id == "d1:0"
    assert top.doc_id == "d1" and top.filename == "d1.md"
    assert "xylophones" in top.text


def test_dense_mode_fallback_matches_pre_v3_behaviour():
    s = _settings(retrieval_mode="dense")
    store = VectorStore(s, collection_name="t_" + os.urandom(4).hex())
    store.load()
    _seed(store, {"d1": ["alpha beta"], "d2": ["gamma delta"]})
    search = HybridSearch(s, FakeEmbedder(), store)
    hits = search.retrieve("alpha", k=2)
    assert hits[0].chunk_id == "d1:0"
    assert all(c.rrf_score is None for c in hits)  # dense mode: no fused scores


# ------------------------------------------------------------------ scoping + rebuild

def test_doc_ids_scope_both_lexical_and_dense():
    s = _settings()
    store = VectorStore(s, collection_name="t_" + os.urandom(4).hex())
    store.load()
    _seed(store, {
        "a": ["Secret alpha documents in scenario A"],
        "b": ["Secret alpha documents in scenario B"],
    })
    search = HybridSearch(s, FakeEmbedder(), store)
    hits = search.retrieve("secret alpha", k=2, doc_ids=["a"])
    assert {c.doc_id for c in hits} == {"a"}


def test_lexical_index_rebuilds_on_store_revision_change():
    s = _settings()
    store = VectorStore(s, collection_name="t_" + os.urandom(4).hex())
    store.load()
    _seed(store, {"d1": ["original passage text"]})
    search = HybridSearch(s, FakeEmbedder(), store)
    hits = search.retrieve("original passage", k=3)
    assert hits[0].chunk_id == "d1:0"

    _seed(store, {"d1": ["completely replaced text"]})   # upsert bumps revision
    hits2 = search.retrieve("completely replaced", k=3)
    assert hits2[0].chunk_id == "d1:0"
    # old content must no longer win the lexical ranking
    old = [c for c in search.retrieve("original passage", k=3)]
    assert all(c.chunk_id != "d1:0" or "original" not in c.text.lower() for c in old)

    # delete bumps revision too: deleted content must disappear from lexical
    store.delete_document("d1")
    assert search.retrieve("completely replaced", k=3) == []


def test_scenario_reset_cycle_updates_index():
    """Bench _reset_scenario: delete docs then re-ingest SAME doc ids count —
    the revision counter (not count) must trigger the rebuild."""
    s = _settings()
    store = VectorStore(s, collection_name="t_" + os.urandom(4).hex())
    store.load()
    _seed(store, {"s1": ["squad article one about gravity"],
                  "s2": ["squad article two about photosynthesis"]})
    search = HybridSearch(s, FakeEmbedder(), store)
    search.retrieve("gravity", k=2)  # builds the index for (rev, "*")

    store.delete_document("s1")                     # scenario reset: delete
    _seed(store, {"s1": ["hotpot article about pyramids"]})  # re-ingest (count restored)
    hits = search.retrieve("pyramids", k=2)
    assert hits and hits[0].chunk_id == "s1:0"
    assert "pyramids" in hits[0].text


def test_index_reused_when_unchanged():
    s = _settings()
    store = VectorStore(s, collection_name="t_" + os.urandom(4).hex())
    store.load()
    _seed(store, {"d1": ["stable content"]})
    search = HybridSearch(s, FakeEmbedder(), store)
    search.retrieve("stable", k=1)
    marker = search._built_for
    search.retrieve("stable", k=1)
    assert search._built_for == marker  # no mutation -> no rebuild


# ------------------------------------------------------------------ ingestion chunking

def test_ingestor_split_uses_contextual_prefix():
    from app.rag.ingestion import Ingestor

    s = _settings(contextual_prefix=True)
    ing = Ingestor(s, FakeEmbedder(), VectorStore(s))
    text = "# Handbook\n\nAlpha section.\n\n## Details\n\nBeta paragraph."
    chunks = ing._split(text, "handbook.md")
    assert any("handbook" in c.lower() for c in chunks)
    assert any("Details" in c for c in chunks)
    assert any("Beta paragraph" in c for c in chunks)


def test_ingestor_split_plain_without_prefix():
    from app.rag.ingestion import Ingestor

    s = _settings(contextual_prefix=False)
    ing = Ingestor(s, FakeEmbedder(), VectorStore(s))
    chunks = ing._split("Plain text without headings. " * 50, "doc.txt")
    assert chunks and all("doc.txt ::" not in c for c in chunks)
