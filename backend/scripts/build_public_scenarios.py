#!/usr/bin/env python3
"""build_public_scenarios.py — materialize popular public RAG benchmarks
as internal bench scenarios.

Benchmarks
----------
1. SQuAD v1.1 dev            (single-hop, full-article corpus)
2. HotpotQA dev-distractor    (multi-hop bridge/comparison, 10-para contexts)
3. TriviaQA rc.wikipedia val  (single-hop open-domain, wiki evidence pages)
4. 2WikiMultiHopQA val        (multi-hop incl. structured triple evidence)
5. MuSiQue-Ans val            (compositional multi-hop, adversarial distractors)

What it does
------------
1. Reads the raw datasets from backend/data/public_bench/raw/ (downloaded
   manually — see PROVENANCE in the manifest for URLs).
2. Samples a fixed, seed-reproducible question subset from each:
     - SQuAD: 25 questions, one per distinct article (topic spread).
     - HotpotQA: 25 questions stratified by type (18 bridge / 7 comparison),
       each answered from the 10-paragraph distractor context.
     - TriviaQA: 16 questions with verified answer-in-page wiki evidence;
       corpus padded to ~64 docs with other questions' wiki pages.
     - 2WikiMultiHopQA: 16 questions stratified by type (7 compositional / 4
       comparison / 3 bridge-comparison / 2 inference), union-of-contexts corpus.
     - MuSiQue: 16 questions stratified by hops (8 two-hop / 5 three-hop /
       3 four-hop), union-of-paragraphs corpus with adversarial distractors.
3. Writes corpus markdown files into backend/app/bench/corpora/<scenario>/ and a
   manifest (public_benchmarks.json) that app/bench/scenarios.py auto-loads.

Merge semantics: re-running WITHOUT --force keeps already-built scenarios
byte-identical in the manifest (their committed corpora stay untouched) and
only appends benchmarks that are missing. --force rebuilds everything from
raw data (all raw files must then be present).

Design notes (kept honest for the write-up):
- Corpus granularity matches the internal scenarios: one file per document;
  gold_files lists the files whose text contains the answer. Retrieval metrics
  are therefore file-level (same yardstick as the internal suite).
- No file carries any marker of being gold vs distractor — contents are the
  verbatim dataset text, so neither arm (nor the judge) can tell.
- All five datasets are fully answerable; the abstention axis stays covered by
  the internal outofscope scenario. References are the datasets' gold answers.

Run:  python3 backend/scripts/build_public_scenarios.py [--force]
"""
from __future__ import annotations

import json
import random
import re
import sys
import unicodedata
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
RAW = BACKEND / "data" / "public_bench" / "raw"
CORPORA = BACKEND / "app" / "bench" / "corpora"
MANIFEST = CORPORA / "public_benchmarks.json"

SEED = 42
SQUAD_N = 25
# Dev distractor is all level='hard' (easy/medium moved to train); stratify by
# type instead, roughly matching the split's 80/20 bridge/comparison ratio.
HOTPOT_N_PER_TYPE = {"bridge": 18, "comparison": 7}  # 25 total
TRIVIA_N = 16                 # gold questions; corpus padded to ~64 docs
TRIVIA_TOTAL_DOCS = 64        # gold evidence pages + distractor pages from other Qs
# 2wiki validation type mix matching the split's actual distribution
# (compositional 41.6% / comparison 24.2% / bridge_comparison 21.9% / inference 12.3%)
W2_N_PER_TYPE = {"compositional": 7, "comparison": 4, "bridge_comparison": 3, "inference": 2}
# MuSiQue hop mix roughly matching the validation distribution — 16 total
MQ_N_PER_HOP = {"2hop": 8, "3hop": 5, "4hop": 3}


def _norm(s: str) -> str:
    return " ".join(str(s).casefold().split())


def slugify(text: str, max_len: int = 48) -> str:
    """ASCII-safe filename slug that stays readable."""
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (s[:max_len].rstrip("-")) or "doc"


def write_doc(corpus_dir: Path, filename: str, title: str, body: str) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    path = corpus_dir / filename
    path.write_text(f"# {title}\n\n{body.strip()}\n", encoding="utf-8")


# ------------------------------------------------------------------ SQuAD
def build_squad() -> tuple[dict, dict]:
    """SQuAD v1.1 dev: 1 question per distinct article, full article as the doc."""
    data = json.loads((RAW / "squad-dev-v1.1.json").read_text(encoding="utf-8"))
    articles = data["data"]
    rng = random.Random(SEED)

    order = list(range(len(articles)))
    rng.shuffle(order)
    picked: list[dict] = []  # {article, qa, para_idx}
    for ai in order:
        art = articles[ai]
        paras = art["paragraphs"]
        if not paras:
            continue
        # choose a paragraph that actually has QAs, then one QA from it
        candidates = [(pi, p) for pi, p in enumerate(paras) if p.get("qas")]
        if not candidates:
            continue
        pi, para = rng.choice(candidates)
        qa = rng.choice(para["qas"])
        if not qa.get("answers"):
            continue
        picked.append({"article": art, "qa": qa, "para_idx": pi})
        if len(picked) >= SQUAD_N:
            break

    if len(picked) < SQUAD_N:
        raise SystemExit(f"FATAL: only {len(picked)} SQuAD articles yielded questions")

    corpus_dir = CORPORA / "squad"
    docs: list[str] = []
    questions: list[dict] = []
    seen_qids: set[str] = set()
    for i, item in enumerate(picked, 1):
        art, qa = item["article"], item["qa"]
        title = art["title"].replace("_", " ").strip()
        fname = f"bench-squad-{i:02d}-{slugify(title)}.md"
        body = "\n\n".join(p["context"].strip() for p in art["paragraphs"])
        write_doc(corpus_dir, fname, title, body)
        docs.append(fname)

        answers = []
        for a in qa["answers"]:
            t = a["text"].strip()
            if t and t not in answers:
                answers.append(t)
        qid = f"sq{i}"
        assert qid not in seen_qids
        seen_qids.add(qid)
        questions.append({
            "id": qid,
            "question": qa["question"].strip(),
            "reference": " / ".join(answers),
            "gold_files": [fname],
            "answerable": True,
            "qtype": "lookup",
            "note": f"SQuAD dev article '{title}' (gold answer in paragraph {item['para_idx'] + 1})",
        })

    return {
        "id": "squad",
        "name": "SQuAD v1.1 (dev sample)",
        "category": "Single-hop factoid QA (public benchmark)",
        "description": (
            "25 seeded-sample questions from the SQuAD v1.1 dev split, one per distinct "
            "Wikipedia article. Corpus = the full articles of the sampled questions."
        ),
        "stresses": (
            "Open-domain-style single-hop retrieval over real Wikipedia prose — the "
            "canonical public reference point (Rajpurkar et al. 2016)."
        ),
        "docs": docs,
        "questions": questions,
    }, {
        "dataset": "SQuAD v1.1 dev",
        "url": "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v1.1.json",
        "split_size": 10570,
        "sample": {"n": len(questions), "seed": SEED, "strategy": "1 question per distinct article"},
    }


# ------------------------------------------------------------------ HotpotQA
def build_hotpot() -> tuple[dict, dict]:
    """HotpotQA dev distractor: 25 questions stratified by type (all dev items are
    level='hard'); corpus = union of all 10-paragraph contexts (deduped by title),
    gold = the 2 supporting titles."""
    import pandas as pd

    df = pd.read_parquet(RAW / "hotpot-dev-distractor.parquet")
    rng = random.Random(SEED)

    picked_idx: list[int] = []
    for qtype, want in HOTPOT_N_PER_TYPE.items():
        idxs = list(df.index[df["type"] == qtype])
        rng.shuffle(idxs)
        taken = 0
        for i in idxs:
            row = df.loc[i]
            titles = set(str(t).strip() for t in row["context"]["title"])
            supp = [str(t).strip() for t in row["supporting_facts"]["title"]]
            if supp and all(t in titles for t in supp):
                picked_idx.append(int(i))
                taken += 1
                if taken >= want:
                    break
        if taken < want:
            raise SystemExit(f"FATAL: hotpot type '{qtype}' yielded only {taken}/{want}")
    rng.shuffle(picked_idx)  # interleave types so the run sees them mixed

    corpus_dir = CORPORA / "hotpotqa"
    title_to_file: dict[str, str] = {}
    docs: list[str] = []
    questions: list[dict] = []
    doc_counter = 0

    for i in picked_idx:
        row = df.loc[i]
        ctx = row["context"]
        supp_titles = list(row["supporting_facts"]["title"])

        # intern all 10 paragraphs of this question's context
        for title, sentences in zip(ctx["title"], ctx["sentences"]):
            title_clean = str(title).strip()
            if title_clean in title_to_file:
                continue
            doc_counter += 1
            fname = f"bench-hotpot-{doc_counter:03d}-{slugify(title_clean)}.md"
            body = " ".join(str(s).strip() for s in sentences if str(s).strip())
            if not body:
                body = f"(empty article: {title_clean})"
            write_doc(corpus_dir, fname, title_clean, body)
            title_to_file[title_clean] = fname
            docs.append(fname)

        # dedup preserving order (supporting_facts repeats a title when both
        # hop-evidence sentences live in the same article)
        gold = list(dict.fromkeys(title_to_file[str(t).strip()] for t in supp_titles))
        qid = f"hp{len(questions) + 1}"
        questions.append({
            "id": qid,
            "question": str(row["question"]).strip(),
            "reference": str(row["answer"]).strip(),
            "gold_files": gold,
            "answerable": True,
            "qtype": "multi-hop",
            "note": (
                f"HotpotQA dev distractor ({row['type']}, {row['level']}) — "
                f"gold titles: {', '.join(str(t) for t in supp_titles)}"
            ),
        })

    n_distractor_docs = len(docs) - 2 * len(questions)  # rough (dedup may overlap gold)
    return {
        "id": "hotpotqa",
        "name": "HotpotQA (dev distractor sample)",
        "category": "Multi-hop factoid QA (public benchmark)",
        "description": (
            "25 seeded-sample questions from the HotpotQA dev distractor split "
            "(18 bridge / 7 comparison; all dev items are level=hard). Corpus = union of "
            "every question's 10-paragraph context (gold + distractors), deduplicated by title."
        ),
        "stresses": (
            "Multi-hop evidence gathering amid hard distractors — the canonical "
            "public multi-hop reference (Yang et al. 2018)."
        ),
        "docs": docs,
        "questions": questions,
    }, {
        "dataset": "HotpotQA dev distractor",
        "url": "https://huggingface.co/datasets/hotpotqa/hotpot_qa (distractor/validation parquet); "
               "original: http://curtis.ml.cmu.edu/datasets/hotpot/",
        "split_size": len(df),
        "sample": {
            "n": len(questions),
            "seed": SEED,
            "strategy": "stratified by type: 18 bridge / 7 comparison (dev split is 100% level=hard)",
            "supporting_facts_verified_in_context": True,
        },
    }


# ------------------------------------------------------------------ TriviaQA
def build_triviaqa() -> tuple[dict, dict]:
    """TriviaQA rc.wikipedia validation: 16 questions whose answer is verifiable
    in a wiki entity page (normalized substring check); corpus = all entity
    pages of the sampled questions + distractor pages from other questions'
    evidence until ~64 docs. Memory-safe: row-group-at-a-time pyarrow reads
    (the 234 MB parquet is never fully materialized)."""
    import pyarrow.parquet as pq

    path = RAW / "triviaqa-rc-wikipedia-validation.parquet"
    pf = pq.ParquetFile(path)
    n_rows = pf.metadata.num_rows
    rg_sizes = [pf.metadata.row_group(i).num_rows for i in range(pf.metadata.num_row_groups)]

    def rg_of(row: int) -> int:
        acc = 0
        for rg, sz in enumerate(rg_sizes):
            acc += sz
            if row < acc:
                return rg
        raise IndexError(row)

    # cache exactly one row group at a time (entity_pages incl. wiki_context)
    cache: dict[int, list[dict]] = {}

    def row(row_i: int) -> dict:
        rg = rg_of(row_i)
        if rg not in cache:
            cache.clear()
            cache[rg] = pf.read_row_group(rg).to_pylist()
        off = row_i - sum(rg_sizes[:rg])
        return cache[rg][off]

    rng = random.Random(SEED)
    order = list(range(n_rows))
    rng.shuffle(order)

    def gold_check(r: dict) -> list[int]:
        """Indices of entity pages whose text (normalized) contains the answer
        value or one of its aliases. Empty list -> question not verifiable."""
        pages = r.get("entity_pages") or {}
        titles = pages.get("title") or []
        texts = pages.get("wiki_context") or []
        ans = r.get("answer") or {}
        values = [str(ans.get("value") or "")]
        values += [str(a) for a in (ans.get("aliases") or []) if a]
        values_n = [_norm(v) for v in values if _norm(v)]
        hits: list[int] = []
        for pi, text in enumerate(texts):
            tn = _norm(text)
            if any(v in tn for v in values_n):
                hits.append(pi)
        return hits

    picked: list[dict] = []      # {row_i, gold_idx (page indices)}
    for row_i in order:
        r = row(row_i)
        pages = r.get("entity_pages") or {}
        if not (pages.get("title") or []):
            continue
        hits = gold_check(r)
        if not hits:
            continue             # answer not verifiable in evidence — skip
        picked.append({"row_i": row_i, "gold_idx": hits, "row": r})
        if len(picked) >= TRIVIA_N:
            break
    if len(picked) < TRIVIA_N:
        raise SystemExit(f"FATAL: only {len(picked)} TriviaQA rows verifiable")

    corpus_dir = CORPORA / "triviaqa"
    title_to_file: dict[str, str] = {}
    docs: list[str] = []
    doc_counter = 0

    def intern_page(title: str, text: str) -> str | None:
        """Write the page once (dedup by title); returns filename or None if
        the page is empty/too small to be a meaningful retrieval unit."""
        nonlocal doc_counter
        title_clean = str(title).strip()
        if title_clean in title_to_file:
            return title_to_file[title_clean]
        body = str(text).strip()
        if len(body) < 80:      # empty/near-empty stubs (TagMe noise) — skip
            return None
        doc_counter += 1
        fname = f"bench-tqa-{doc_counter:03d}-{slugify(title_clean)}.md"
        write_doc(corpus_dir, fname, title_clean, body)
        title_to_file[title_clean] = fname
        docs.append(fname)
        return fname

    questions: list[dict] = []
    for item in picked:
        r = item["row"]
        pages = r.get("entity_pages") or {}
        titles = [str(t).strip() for t in (pages.get("title") or [])]
        texts = [str(t) for t in (pages.get("wiki_context") or [])]
        gold: list[str] = []
        for pi in range(min(len(titles), len(texts))):
            fname = intern_page(titles[pi], texts[pi])
            if fname and pi in item["gold_idx"]:
                gold.append(fname)
        if not gold:             # gold page was a skipped stub — drop question
            continue
        ans = r.get("answer") or {}
        value = str(ans.get("value") or "").strip()
        aliases = [str(a).strip() for a in (ans.get("aliases") or [])
                   if str(a).strip() and str(a).strip() != value][:3]
        qid = f"tq{len(questions) + 1}"
        questions.append({
            "id": qid,
            "question": str(r["question"]).strip(),
            "reference": " / ".join([value] + aliases),
            "gold_files": gold,
            "answerable": True,
            "qtype": "lookup",
            "note": (
                f"TriviaQA rc.wikipedia val — evidence page(s): "
                f"{', '.join(titles[pi] for pi in item['gold_idx'])}"
            ),
        })

    # distractor pages: walk the remaining shuffled rows, interning their pages
    # until the corpus reaches the target size (other questions' wiki evidence)
    picked_rows = {it["row_i"] for it in picked}
    for row_i in order:
        if len(docs) >= TRIVIA_TOTAL_DOCS:
            break
        if row_i in picked_rows:
            continue
        r = row(row_i)
        pages = r.get("entity_pages") or {}
        for title, text in zip(pages.get("title") or [], pages.get("wiki_context") or []):
            intern_page(str(title), str(text))
            if len(docs) >= TRIVIA_TOTAL_DOCS:
                break

    return {
        "id": "triviaqa",
        "name": "TriviaQA (rc.wikipedia validation sample)",
        "category": "Single-hop open-domain QA (public benchmark)",
        "description": (
            f"16 seeded-sample questions from the TriviaQA rc.wikipedia validation split "
            f"with answer-verified wiki evidence. Corpus = the sampled questions' entity "
            f"pages plus other questions' wiki pages as distractors ({len(docs)} docs)."
        ),
        "stresses": (
            "Open-domain-style single-hop retrieval over real trivia quiz questions and "
            "full Wikipedia evidence pages — canonical web-scale QA reference "
            "(Joshi et al. 2017)."
        ),
        "docs": docs,
        "questions": questions,
    }, {
        "dataset": "TriviaQA rc.wikipedia validation",
        "url": "https://huggingface.co/datasets/mandarjoshi/trivia_qa "
               "(rc.wikipedia/validation parquet); original: http://nlp.cs.washington.edu/triviaqa/",
        "split_size": n_rows,
        "sample": {
            "n": len(questions),
            "seed": SEED,
            "strategy": "answer-verified questions from a seeded shuffle; corpus padded "
                        "with other questions' entity pages to ~64 docs",
            "answer_verified_in_evidence": True,
        },
    }


# ------------------------------------------------------- 2WikiMultiHopQA
def build_2wiki() -> tuple[dict, dict]:
    """2WikiMultiHopQA validation: 16 questions stratified by type (7
    compositional / 4 comparison / 3 bridge-comparison / 2 inference, matching
    the split's distribution); corpus = union of the 10-paragraph contexts
    (dedup by title), gold = supporting-facts titles verified present in
    context. Context sentences include the dataset's structured triple lines,
    kept verbatim."""
    import pyarrow.parquet as pq

    rows = pq.ParquetFile(RAW / "2wiki-validation.parquet").read().to_pylist()
    rng = random.Random(SEED)

    picked_idx: list[int] = []
    for qtype, want in W2_N_PER_TYPE.items():
        idxs = [i for i, r in enumerate(rows) if r.get("type") == qtype]
        rng.shuffle(idxs)
        taken = 0
        for i in idxs:
            r = rows[i]
            ctx_titles = {str(t).strip() for t in (r["context"].get("title") or [])}
            supp = [str(t).strip() for t in (r["supporting_facts"].get("title") or [])]
            if supp and all(t in ctx_titles for t in supp):
                picked_idx.append(i)
                taken += 1
                if taken >= want:
                    break
        if taken < want:
            raise SystemExit(f"FATAL: 2wiki type '{qtype}' yielded only {taken}/{want}")
    rng.shuffle(picked_idx)

    corpus_dir = CORPORA / "wiki2"
    title_to_file: dict[str, str] = {}
    docs: list[str] = []
    doc_counter = 0
    questions: list[dict] = []

    for i in picked_idx:
        r = rows[i]
        ctx = r["context"]
        supp_titles = [str(t).strip() for t in (r["supporting_facts"].get("title") or [])]

        for title, sentences in zip(ctx.get("title") or [], ctx.get("sentences") or []):
            title_clean = str(title).strip()
            if title_clean in title_to_file:
                continue
            doc_counter += 1
            fname = f"bench-w2-{doc_counter:03d}-{slugify(title_clean)}.md"
            body = " ".join(str(s).strip() for s in sentences if str(s).strip())
            # near-empty stubs (real 2wiki artifact) are dropped UNLESS they are
            # gold for this question — they carry no retrievable signal either way
            if len(body) < 80 and title_clean not in supp_titles:
                doc_counter -= 1
                continue
            if not body:
                body = f"(empty article: {title_clean})"
            write_doc(corpus_dir, fname, title_clean, body)
            title_to_file[title_clean] = fname
            docs.append(fname)

        gold = list(dict.fromkeys(title_to_file[t] for t in supp_titles))
        qid = f"w2{len(questions) + 1}"
        questions.append({
            "id": qid,
            "question": str(r["question"]).strip(),
            "reference": str(r["answer"]).strip(),
            "gold_files": gold,
            "answerable": True,
            "qtype": "multi-hop",
            "note": (
                f"2WikiMultiHopQA val ({r.get('type')}) — gold titles: "
                f"{', '.join(supp_titles)}; structured triples: "
                f"{' ; '.join(' | '.join(map(str, e)) for e in (r.get('evidences') or [])[:2])}"
            ),
        })

    return {
        "id": "wiki2",
        "name": "2WikiMultiHopQA (validation sample)",
        "category": "Multi-hop QA over structured + text evidence (public benchmark)",
        "description": (
            "16 seeded-sample questions from the 2WikiMultiHopQA validation split "
            "(7 compositional / 4 comparison / 3 bridge-comparison / 2 inference, matching "
            "the split's type distribution). Corpus = union of every question's "
            "10-paragraph context (incl. Wikidata triple sentences), deduplicated by title."
        ),
        "stresses": (
            "Multi-hop reasoning that mixes textual and structured (subject | relation | "
            "object) evidence — the standard second multi-hop reference after HotpotQA "
            "(Ho et al. 2020)."
        ),
        "docs": docs,
        "questions": questions,
    }, {
        "dataset": "2WikiMultiHopQA validation",
        "url": "https://huggingface.co/datasets/framolfese/2WikiMultihopQA "
               "(validation parquet); original: https://github.com/Alab-NII/2wikimultihop",
        "split_size": len(rows),
        "sample": {
            "n": len(questions),
            "seed": SEED,
            "strategy": "stratified by type matching the split distribution: "
                        "7 compositional / 4 comparison / 3 bridge-comparison / 2 inference",
            "supporting_facts_verified_in_context": True,
        },
    }


# ------------------------------------------------------------------ MuSiQue
def build_musique() -> tuple[dict, dict]:
    """MuSiQue-Ans validation: 16 answerable questions stratified by hop count
    (8 two-hop / 5 three-hop / 3 four-hop); corpus = union of the 20-paragraph
    contexts (dedup by title), gold = is_supporting paragraphs. MuSiQue's
    distractors are deliberately topically-related (adversarial)."""
    import pyarrow.parquet as pq

    rows = pq.ParquetFile(RAW / "musique-validation.parquet").read().to_pylist()
    rng = random.Random(SEED)

    def hops(r: dict) -> str:
        """Hop class from the id prefix ('2hop', '3hop1'/'3hop2' -> '3hop', ...)."""
        prefix = str(r["id"]).split("__", 1)[0]
        if prefix.startswith("2hop"):
            return "2hop"
        if prefix.startswith("3hop"):
            return "3hop"
        if prefix.startswith("4hop"):
            return "4hop"
        return prefix

    picked_idx: list[int] = []
    for hop, want in MQ_N_PER_HOP.items():
        idxs = [i for i, r in enumerate(rows)
                if hops(r) == hop and r.get("answerable")]
        rng.shuffle(idxs)
        taken = 0
        for i in idxs:
            r = rows[i]
            paras = r.get("paragraphs") or []
            supp = [p for p in paras if p.get("is_supporting")]
            if supp and all(p.get("paragraph_text", "").strip() for p in supp):
                picked_idx.append(i)
                taken += 1
                if taken >= want:
                    break
        if taken < want:
            raise SystemExit(f"FATAL: musique hop '{hop}' yielded only {taken}/{want}")
    rng.shuffle(picked_idx)

    corpus_dir = CORPORA / "musique"
    title_to_file: dict[str, str] = {}
    docs: list[str] = []
    doc_counter = 0
    questions: list[dict] = []

    for i in picked_idx:
        r = rows[i]
        gold_titles: list[str] = []
        for p in r.get("paragraphs") or []:
            title_clean = str(p.get("title") or "").strip()
            text = str(p.get("paragraph_text") or "").strip()
            if title_clean in title_to_file:
                if p.get("is_supporting"):
                    gold_titles.append(title_clean)
                continue
            doc_counter += 1
            fname = f"bench-mq-{doc_counter:03d}-{slugify(title_clean)}.md"
            write_doc(corpus_dir, fname, title_clean, text or f"(empty: {title_clean})")
            title_to_file[title_clean] = fname
            docs.append(fname)
            if p.get("is_supporting"):
                gold_titles.append(title_clean)
        gold = list(dict.fromkeys(title_to_file[t] for t in gold_titles))

        value = str(r["answer"]).strip()
        aliases = [str(a).strip() for a in (r.get("answer_aliases") or [])
                   if str(a).strip() and str(a).strip() != value][:3]
        qid = f"mq{len(questions) + 1}"
        questions.append({
            "id": qid,
            "question": str(r["question"]).strip(),
            "reference": " / ".join([value] + aliases),
            "gold_files": gold,
            "answerable": True,
            "qtype": "multi-hop",
            "note": (
                f"MuSiQue-Ans val ({hops(r)}) — {len(gold)} supporting paragraph(s): "
                f"{', '.join(gold_titles)}; decomposition: "
                f"{' -> '.join(d.get('question', '') for d in (r.get('question_decomposition') or []))}"
            ),
        })

    return {
        "id": "musique",
        "name": "MuSiQue-Ans (validation sample)",
        "category": "Compositional multi-hop QA (public benchmark)",
        "description": (
            "16 seeded-sample questions from the MuSiQue-Ans validation split "
            "(8 two-hop / 5 three-hop / 3 four-hop). Corpus = union of every question's "
            "20-paragraph context, deduplicated by title — distractors are topically "
            "related to the question by construction."
        ),
        "stresses": (
            "Compositional multi-hop reasoning over adversarially-chosen distractors "
            "(MuSiQue explicitly filters out shortcuts) — the hardest multi-hop "
            "reference in this suite (Trivedi et al. 2022)."
        ),
        "docs": docs,
        "questions": questions,
    }, {
        "dataset": "MuSiQue-Ans validation",
        "url": "https://huggingface.co/datasets/dgslibisey/MuSiQue "
               "(validation parquet); original: https://github.com/StonyBrookNLP/musique",
        "split_size": len(rows),
        "sample": {
            "n": len(questions),
            "seed": SEED,
            "strategy": "answerable rows stratified by hop class (id prefix): "
                        "8 two-hop / 5 three-hop / 3 four-hop — split is 52/31/17",
            "supporting_paragraphs_verified_nonempty": True,
        },
    }


# ------------------------------------------------------------------ main
def main() -> None:
    force = "--force" in sys.argv
    existing: dict = {}
    if MANIFEST.exists():
        if force:
            print("--force: rebuilding every scenario from raw data")
            existing = {"generated": "2026-09-28", "provenance": {}, "scenarios": []}
        else:
            existing = json.loads(MANIFEST.read_text(encoding="utf-8"))
    else:
        existing = {"generated": "2026-09-28", "provenance": {}, "scenarios": []}

    scenarios: list[dict] = list(existing.get("scenarios", []))
    provenance: dict = dict(existing.get("provenance", {}))
    built_ids = {s["id"] for s in scenarios}

    builders: list[tuple[str, object]] = [
        ("squad", build_squad), ("hotpotqa", build_hotpot),
        ("triviaqa", build_triviaqa), ("wiki2", build_2wiki),
        ("musique", build_musique),
    ]
    for sid, fn in builders:
        if sid in built_ids:
            print(f"[{sid}] already in manifest — keeping existing corpus verbatim")
            continue
        sc, prov = fn()
        scenarios.append(sc)
        provenance[sid] = prov

    order = ["squad", "hotpotqa", "triviaqa", "wiki2", "musique"]
    scenarios.sort(key=lambda s: order.index(s["id"]))
    manifest = {
        "generated": existing.get("generated", "2026-09-28"),
        "extended": "2026-09-28",
        "provenance": provenance,
        "scenarios": scenarios,
    }
    CORPORA.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    for s in scenarios:
        total_chars = sum(
            (CORPORA / s["id"] / f).stat().st_size for f in s["docs"])
        print(f"[{s['id']}] {len(s['docs'])} docs "
              f"({total_chars / 1000:.0f} KB corpus), {len(s['questions'])} questions")
        gcounts = [len(q['gold_files']) for q in s['questions']]
        print(f"  gold files/question: min {min(gcounts)}, max {max(gcounts)}")
    print(f"manifest -> {MANIFEST}")


if __name__ == "__main__":
    main()
