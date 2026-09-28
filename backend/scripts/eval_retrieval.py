#!/usr/bin/env python3
"""Layer-1 retrieval testbench (offline — no cloud LLM calls).

Evaluates retrieval arms on the public benchmark scenarios and calibrates the
v3 escalation-gate threshold from data (docs/testbench-design.md §Layer 1).

Arms: dense | bm25 | rrf | rrf-cross | rrf-jev | dense-cross | bge-cross
Metrics: recall@4, hit@1, MRR@10, nDCG@10 vs gold files (file-level, same
functions as the main bench) + paired stats vs rrf-cross (exact McNemar on
gold-in-top-4, paired bootstrap CI on recall@4).

Gate calibration: per-question top-1 cross-encoder score (after RRF+rerank)
with the label "gold in top-4" -> best_threshold (Youden J) + accuracy,
Brier, ECE at that operating point.

Usage (from backend/, hermetic to the repo):
  .venv/bin/python scripts/eval_retrieval.py [--scenarios squad,hotpotqa]
      [--arms rrf-cross,dense] [--skip-jev] [--skip-bge] [--out results.json]

Output: JSON (default backend/data/testbench/retrieval_eval.json) + stdout
tables. RAM note: bge-cross re-embeds the corpora with bge-small-en-v1.5 into
a SEPARATE chroma collection; jev arm reuses the running engine subprocess.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: F401  (package init)
from app.bench.metrics import retrieval_metrics  # noqa: E402
from app.bench.scenarios import SCENARIO_MAP, doc_path  # noqa: E402
from app.bench.stats import best_threshold, brier_score, ece, mcnemar_exact, paired_bootstrap_ci  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Document, db_session, init_db  # noqa: E402
from app.llm.jev_engine import JevEngine  # noqa: E402
from app.rag.crossenc import CrossEncoderReranker  # noqa: E402
from app.rag.ingestion import Ingestor  # noqa: E402
from app.rag.lexical import LexicalIndex, rrf_fuse  # noqa: E402
from app.rag.retriever import Embedder, VectorStore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eval_retrieval")

DEFAULT_ARMS = ["dense", "bm25", "rrf", "rrf-cross", "rrf-jev", "dense-cross", "bge-cross"]
K_RETRIEVE = 10   # candidate pool (top_k_retrieve)
K_USE = 4         # kept passages (top_k_use)
RRF_K = 60


def _top_files(chunks: list[dict]) -> list[str]:
    return [c["filename"] for c in chunks]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default="squad,hotpotqa,triviaqa,wiki2,musique")
    parser.add_argument("--arms", default=",".join(DEFAULT_ARMS))
    parser.add_argument("--skip-jev", action="store_true", help="skip the rrf-jev arm")
    parser.add_argument("--skip-bge", action="store_true", help="skip the bge-cross arm")
    parser.add_argument("--out", default="")
    parser.add_argument("--resume", action="store_true",
                        help="load --out and only evaluate missing (scenario, arm) pairs")
    parser.add_argument("--aggregate-only", action="store_true",
                        help="never evaluate: recompute aggregates/stats/report from stored rows")
    args = parser.parse_args()

    scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    if args.skip_jev:
        arms = [a for a in arms if a != "rrf-jev"]
    if args.skip_bge:
        arms = [a for a in arms if a != "bge-cross"]

    settings = get_settings()
    init_db()

    store = VectorStore(settings)
    store.load()
    embedder = Embedder(settings)
    if not embedder.load():
        print(f"FATAL: embedding model failed to load: {embedder.info()}", file=sys.stderr)
        return 1
    ingestor = Ingestor(settings, embedder, store)

    # alternate embedding space for the bge arm (separate collection)
    bge_embedder = None
    bge_store = None
    if "bge-cross" in arms:
        bge_settings = _clone_settings(settings, embed_model="BAAI/bge-small-en-v1.5")
        bge_embedder = Embedder(bge_settings)
        if bge_embedder.load():
            bge_store = VectorStore(bge_settings, collection_name="jevrag_bge_eval")
            bge_store.load()
        else:
            logger.warning("bge-small-en-v1.5 failed to load — dropping bge-cross arm")
            arms = [a for a in arms if a != "bge-cross"]

    reranker = CrossEncoderReranker(model_name=settings.reranker_model,
                                    cache_dir=(settings.reranker_cache_dir or None))
    if "rrf-cross" in arms or "dense-cross" in arms or "bge-cross" in arms:
        if not reranker.load():
            logger.warning("cross-encoder failed to load — dropping cross arms")
            arms = [a for a in arms if not a.endswith("-cross")]

    jev = None
    if "rrf-jev" in arms:
        jev = JevEngine(settings)
        if not jev.load():
            logger.warning("jev engine failed to load — dropping rrf-jev arm")
            arms = [a for a in arms if a != "rrf-jev"]

    out_path = Path(args.out or (settings.data_dir / "testbench" / "retrieval_eval.json"))

    # resume support: keep prior per-question rows; re-evaluate only missing
    # (scenario, arm) pairs. Aggregates + stats are always recomputed fresh.
    prior: dict = {}
    if (args.resume or args.aggregate_only) and out_path.exists():
        try:
            prior = json.loads(out_path.read_text())
            logger.info("resumed %s: %d arm(s) with data", out_path, len(prior.get("arms", {})))
        except Exception as e:  # noqa: BLE001
            logger.warning("could not load prior results (%s) — starting fresh", e)
    results: dict = {"arms": prior.get("arms", {}), "gate_calibration": {},
                     "meta": {"scenarios": scenario_ids, "arms": arms,
                              "k_retrieve": K_RETRIEVE, "k_use": K_USE, "rrf_k": RRF_K,
                              "resumed_from": str(out_path) if prior else None,
                              "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}}
    # NOTE: arms NOT requested in this invocation keep their stored data
    # (subset runs extend, never shrink, the accumulated results).
    gate_scores: list[float] = []
    gate_labels: list[int] = []
    bge_lex = None

    for sid in scenario_ids:
        scenario = SCENARIO_MAP.get(sid)
        if scenario is None:
            print(f"unknown scenario {sid}", file=sys.stderr)
            return 2
        # aggregate-only mode: collect gate calibration rows, never re-evaluate
        if args.aggregate_only:
            for q in scenario.questions:
                row = (results["arms"].get("rrf-cross", {})
                       .get("per_scenario", {}).get(sid, {}).get("per_question", {}).get(q.id))
                if row and "gate_top1" in row:
                    gate_scores.append(row["gate_top1"])
                    gate_labels.append(row["gate_label"])
            continue
        # skip scenarios whose every requested arm already has data
        missing_arms = [a for a in arms
                        if not _has_all_questions(results, a, sid, scenario)]
        if not missing_arms:
            logger.info("[%s] all arms already evaluated — skipping (resume)", sid)
            for q in scenario.questions:  # rebuild gate calibration from stored rows
                row = results["arms"]["rrf-cross"]["per_scenario"][sid]["per_question"].get(q.id)
                if row and "gate_top1" in row:
                    gate_scores.append(row["gate_top1"])
                    gate_labels.append(row["gate_label"])
            continue
        doc_ids = _reset_scenario(ingestor, scenario)
        lex = _build_lexical(store, doc_ids)
        bge_doc_ids: list[str] | None = None
        if bge_store is not None and any(a == "bge-cross" for a in missing_arms):
            bge_doc_ids = _reset_bge(bge_store, bge_embedder, scenario, settings)
            bge_lex = _build_lexical(bge_store, bge_doc_ids)

        def _save():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(results, indent=2))

        for arm in missing_arms:
            per_q = results["arms"].setdefault(arm, {"per_scenario": {}})
            scenario_row = per_q["per_scenario"].setdefault(sid, {"per_question": {}})
            prior_rows = (prior.get("arms", {}).get(arm, {})
                          .get("per_scenario", {}).get(sid, {}).get("per_question", {}))
            scenario_row["per_question"].update(prior_rows)
            arm_rows = scenario_row["per_question"]

            for q in scenario.questions:
                if q.id in arm_rows:  # already evaluated (resume)
                    row = arm_rows[q.id]
                    if arm == "rrf-cross" and "gate_top1" in row:
                        gate_scores.append(row["gate_top1"])
                        gate_labels.append(row["gate_label"])
                    continue
                cands = _retrieve_arm(arm, q.question, doc_ids, store, embedder, lex,
                                      bge_store, bge_embedder, bge_lex, bge_doc_ids)
                kept = _rerank_arm(arm, q.question, cands, reranker, jev, settings)
                kept = kept[:K_USE]
                files = _top_files(kept)
                gold = list(q.gold_files)
                metrics = retrieval_metrics(files, gold) if gold else {}
                row = {"files": files, "metrics": metrics}
                if arm == "rrf-cross":
                    top1 = float(kept[0].get("jev_score", 0.0)) if kept else 0.0
                    label = 1 if metrics.get("recall4", 0) >= 1.0 else 0
                    row["gate_top1"] = top1
                    row["gate_label"] = label
                    gate_scores.append(top1)
                    gate_labels.append(label)
                arm_rows[q.id] = row
            agg = _aggregate([v["metrics"] for v in arm_rows.values()])
            scenario_row.update(agg)
            _save()  # incremental: window timeouts never lose completed work
            logger.info("[%s/%s] recall4=%.3f hit1=%.3f", arm, sid, agg["recall4"], agg["hit1"])

    # pooled aggregates + paired stats vs the v3 default (rrf-cross)
    reference = "rrf-cross" if "rrf-cross" in arms else arms[0] if arms else None

    def _rows(arm: str, sid: str) -> dict:
        try:
            return results["arms"][arm]["per_scenario"][sid]["per_question"]
        except KeyError:
            return {}

    for arm in arms:
        all_metrics = [v["metrics"] for sid in scenario_ids
                       for v in _rows(arm, sid).values()]
        results["arms"][arm].update(_aggregate(all_metrics))
    if reference and reference in results["arms"] and len(arms) > 1:
        for arm in arms:
            if arm == reference:
                continue
            stats = _paired_vs_reference(
                {sid: _rows(arm, sid) for sid in scenario_ids},
                {sid: _rows(reference, sid) for sid in scenario_ids})
            results["arms"][arm]["vs_reference"] = stats

    # gate calibration from rrf-cross scores
    if gate_scores:
        bt = best_threshold(gate_scores, gate_labels)
        thr = bt["threshold"] if bt else 0.5
        preds = [1 if s >= thr else 0 for s in gate_scores]
        acc = sum(p == l for p, l in zip(preds, gate_labels)) / len(gate_labels)
        results["gate_calibration"] = {
            "n": len(gate_labels), "positive_rate": round(sum(gate_labels) / len(gate_labels), 4),
            "recommended_threshold": round(thr, 4),
            "youden_j": round(bt["youden_j"], 4) if bt else None,
            "accuracy_at_threshold": round(acc, 4),
            "brier": round(brier_score(gate_scores, gate_labels), 4),
            "ece": round(ece(gate_scores, gate_labels), 4),
            "note": "top-1 cross-encoder score vs label gold-in-top-4; "
                    "recommended_threshold feeds JEVRAG_GATE_SCORE_THRESHOLD",
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    _print_report(results, reference)
    print(f"\nsaved: {out_path}")
    return 0


def _has_all_questions(results: dict, arm: str, sid: str, scenario) -> bool:
    try:
        rows = results["arms"][arm]["per_scenario"][sid]["per_question"]
    except KeyError:
        return False
    return all(q.id in rows for q in scenario.questions)


def _clone_settings(settings, **over):
    from app.config import Settings
    fields = {f: getattr(settings, f) for f in settings.model_fields}
    fields.update(over)
    fields["_env_file"] = None
    return Settings(**fields)


def _reset_scenario(ingestor: Ingestor, scenario) -> list[str]:
    from sqlalchemy import select
    doc_ids: list[str] = []
    with db_session() as session:
        for filename in scenario.docs:
            for doc in session.execute(
                    select(Document).where(Document.filename == filename)).scalars().all():
                ingestor.delete_document(session, doc.id)
        session.commit()
        for filename in scenario.docs:
            path = doc_path(scenario.id, filename)
            doc = ingestor.ingest_file(session, path, filename=filename,
                                       file_size=path.stat().st_size)
            if doc.status != "ready":
                raise RuntimeError(f"ingestion failed for {filename}: {doc.error}")
            doc_ids.append(doc.id)
        session.commit()
    return doc_ids


def _reset_bge(bge_store: VectorStore, bge_embedder: Embedder, scenario,
               settings) -> list[str]:
    """Ingest the scenario corpus into the bge eval collection WITHOUT touching
    the shared documents table (the main-store reset owns those rows). Chunks
    are deleted by filename metadata; doc ids are deterministic per scenario
    so repeated resets are idempotent."""
    from app.rag.ingestion import Ingestor
    from app.db import db_session  # noqa: F401 — bge path never writes Document rows

    tmp_ing = Ingestor(settings, bge_embedder, bge_store)  # reuses extract/_split
    bge_store._ensure()
    for filename in scenario.docs:
        bge_store._collection.delete(where={"filename": filename})
    doc_ids: list[str] = []
    for filename in scenario.docs:
        path = doc_path(scenario.id, filename)
        text = tmp_ing._extract_text(path).strip()
        if not text:
            raise RuntimeError(f"no text extracted for {filename}")
        chunks = tmp_ing._split(text, filename)
        embeddings = bge_embedder.embed_documents(chunks)
        doc_id = f"bge-{scenario.id}-{len(doc_ids)}"
        bge_store.add_chunks(doc_id, filename, chunks, embeddings)
        doc_ids.append(doc_id)
    logger.info("bge eval corpus ready: %s (%d docs)", scenario.id, len(doc_ids))
    return doc_ids


def _build_lexical(store: VectorStore, doc_ids: list[str]) -> LexicalIndex:
    lex = LexicalIndex(k1=1.5, b=0.75)
    lex.build(store.all_chunks(doc_ids))
    return lex


def _retrieve_arm(arm, query, doc_ids, store, embedder, lex,
                  bge_store=None, bge_embedder=None, bge_lex=None,
                  bge_doc_ids=None) -> list[dict]:
    """Candidate pool (K_RETRIEVE) per arm; returns list[dict]."""
    if arm == "dense" or arm == "dense-cross":
        return _chunks_to_dicts(store.query(embedder.embed_query(query), K_RETRIEVE, doc_ids=doc_ids))
    if arm == "bge-cross":
        return _chunks_to_dicts(bge_store.query(bge_embedder.embed_query(query), K_RETRIEVE,
                                                doc_ids=bge_doc_ids or doc_ids))
    if arm == "bm25":
        out = []
        for cid, _score in lex.query(query, top_n=K_RETRIEVE):
            out.append({"chunk_id": cid})
        return _hydrate(store, out)
    # rrf family: fuse dense + lexical rankings
    dense = store.query(embedder.embed_query(query), K_RETRIEVE, doc_ids=doc_ids)
    lexical = lex.query(query, top_n=K_RETRIEVE)
    fused = rrf_fuse([[c.chunk_id for c in dense], [cid for cid, _ in lexical]], rrf_k=RRF_K)
    return _hydrate(store, [{"chunk_id": cid} for cid in fused[:K_RETRIEVE]])


def _chunks_to_dicts(chunks) -> list[dict]:
    out = []
    for i, c in enumerate(chunks):
        d = c.as_dict()
        d["retrieval_rank"] = i + 1
        d["index"] = i + 1
        out.append(d)
    return out


def _hydrate(store: VectorStore, partial: list[dict]) -> list[dict]:
    """Attach text/metadata to chunk_id-only dicts (from BM25/RRF arms)."""
    by_id = {c.chunk_id: c for c in store.get_chunks_by_ids([p["chunk_id"] for p in partial])}
    out = []
    for i, p in enumerate(partial):
        c = by_id.get(p["chunk_id"])
        if c is None:
            continue
        d = c.as_dict()
        d["retrieval_rank"] = i + 1
        d["index"] = i + 1
        out.append(d)
    return out


def _rerank_arm(arm, query, cands, reranker, jev, settings) -> list[dict]:
    if not cands:
        return []
    if arm in ("rrf-cross", "dense-cross", "bge-cross"):
        scores = reranker.score_pairs(
            query, [c.get("text", "")[: settings.jev_rerank_char_limit] for c in cands])
        if scores is None:
            return cands
        for c, sc in zip(cands, scores):
            c["jev_score"] = round(sc, 4)
        return sorted(cands, key=lambda c: c["jev_score"], reverse=True)
    if arm == "rrf-jev":
        ranked, _rec = jev.rerank_chunks(query, cands, settings.jev_rerank_char_limit)
        return ranked
    return cands  # dense / bm25 / rrf: retrieval order


def _aggregate(metrics: list[dict]) -> dict:
    keys = ("hit1", "hit4", "hit10", "mrr", "recall4", "recall10", "ndcg10")
    out = {"n": len(metrics)}
    for k in keys:
        vals = [m.get(k) for m in metrics if m.get(k) is not None]
        out[k] = round(sum(vals) / len(vals), 4) if vals else None
    return out


def _paired_vs_reference(arm_q: dict, ref_q: dict) -> dict:
    """McNemar on gold-in-top4 + bootstrap CI on recall4, per question."""
    b = c = 0
    diffs: list[float] = []
    for sid in arm_q:
        for qid, row in arm_q[sid].items():
            ref_row = ref_q.get(sid, {}).get(qid)
            if ref_row is None:
                continue
            arm_m = row.get("metrics", {})
            ref_m = ref_row.get("metrics", {})
            arm_ok = 1 if arm_m.get("recall4", 0) >= 1.0 else 0
            ref_ok = 1 if ref_m.get("recall4", 0) >= 1.0 else 0
            if arm_ok and not ref_ok:
                b += 1
            elif ref_ok and not arm_ok:
                c += 1
            diffs.append(arm_m.get("recall4", 0.0) - ref_m.get("recall4", 0.0))
    boot = paired_bootstrap_ci(diffs, stat="mean", n_resamples=50000, seed=42)
    return {"mcnemar_b": b, "mcnemar_c": c, "p_mcnemar": round(mcnemar_exact(b, c), 4),
            "recall4_delta": round(boot["point"], 4),
            "recall4_delta_ci95": [round(boot["lo"], 4), round(boot["hi"], 4)]}


def _print_report(results: dict, reference: str | None) -> None:
    print(f"\n{'arm':<12} {'recall4':>8} {'hit1':>7} {'mrr':>7} {'ndcg10':>8}   vs {reference}")
    print("-" * 70)
    for arm, data in results["arms"].items():
        vs = ""
        stats = data.get("vs_reference")
        if stats:
            vs = (f"Δrecall4 {stats['recall4_delta']:+.3f} "
                  f"CI {stats['recall4_delta_ci95'][0]:+.3f}..{stats['recall4_delta_ci95'][1]:+.3f} "
                  f"p={stats['p_mcnemar']:.3f}")
        print(f"{arm:<12} {data.get('recall4') or 0:>8} {data.get('hit1') or 0:>7} "
              f"{data.get('mrr') or 0:>7} {data.get('ndcg10') or 0:>8}   {vs}")
    gc = results.get("gate_calibration")
    if gc:
        print(f"\ngate calibration (top-1 cross score vs gold-in-top4): "
              f"n={gc['n']}, θ*={gc['recommended_threshold']} (Youden J={gc.get('youden_j')}), "
              f"acc@θ*={gc['accuracy_at_threshold']}, Brier={gc['brier']}, ECE={gc['ece']}")


if __name__ == "__main__":
    raise SystemExit(main())
