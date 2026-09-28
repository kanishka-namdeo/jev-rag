#!/usr/bin/env python3
"""build_public_scenarios.py — materialize two popular public RAG benchmarks
(SQuAD v1.1 dev, HotpotQA dev-distractor) as internal bench scenarios.

What it does
------------
1. Reads the raw datasets from backend/data/public_bench/raw/ (downloaded by
   scripts/download_public_bench.sh / manually — see PROVENANCE in the manifest).
2. Samples a fixed, seed-reproducible question subset from each:
     - SQuAD: 25 questions, one per distinct article (topic spread).
     - HotpotQA: 25 questions stratified over level (easy/medium/hard), each
       answered from the 10-paragraph distractor context (2 gold + 8 distractors).
3. Writes corpus markdown files into backend/app/bench/corpora/<scenario>/ and a
   manifest (public_benchmarks.json) that app/bench/scenarios.py auto-loads.

Design notes (kept honest for the write-up):
- Corpus granularity matches the internal scenarios: one file per document;
  gold_files lists the files whose text contains the answer. Retrieval metrics
  are therefore file-level (same yardstick as the internal suite).
- No file carries any marker of being gold vs distractor — contents are the
  verbatim dataset text, so neither arm (nor the judge) can tell.
- Both datasets are fully answerable; the abstention axis stays covered by the
  internal outofscope scenario. References are the datasets' gold answers.

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


# ------------------------------------------------------------------ main
def main() -> None:
    force = "--force" in sys.argv
    if MANIFEST.exists() and not force:
        print(f"manifest already exists ({MANIFEST}); use --force to rebuild")
        return

    squad_scenario, squad_prov = build_squad()
    hotpot_scenario, hotpot_prov = build_hotpot()

    manifest = {
        "generated": "2026-09-28",
        "provenance": {"squad": squad_prov, "hotpotqa": hotpot_prov},
        "scenarios": [squad_scenario, hotpot_scenario],
    }
    CORPORA.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    for s in (squad_scenario, hotpot_scenario):
        total_chars = sum(
            (CORPORA / s["id"] / f).stat().st_size for f in s["docs"])
        print(f"[{s['id']}] {len(s['docs'])} docs "
              f"({total_chars / 1000:.0f} KB corpus), {len(s['questions'])} questions")
        gcounts = [len(q['gold_files']) for q in s['questions']]
        print(f"  gold files/question: min {min(gcounts)}, max {max(gcounts)}")
    print(f"manifest -> {MANIFEST}")


if __name__ == "__main__":
    main()
