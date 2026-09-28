"""Tests for app.rag.lexical — BM25 lexical index + RRF fusion.

Run: cd backend && .venv/bin/python -m pytest tests/test_lexical.py -q

Hermetic: stdlib-only module under test, no models, no network, no disk.

Verification strategy: BM25 scores are checked against a REFERENCE
implementation of the same formula (``_ref_bm25`` below) fed with tf/df/dl
statistics that are HAND-COUNTED from the toy corpora (documented inline).
The reference is intentionally written from the spec formula, not by
calling the module under test, so these are hand-verifications, not
tautologies.
"""
from __future__ import annotations

import math

import pytest

from app.rag.lexical import LexicalIndex, rrf_fuse, tokenize

# BM25 defaults used by LexicalIndex (k1=1.5, b=0.75) — mirrored here only
# to keep the reference scorer explicit.
K1 = 1.5
B = 0.75


def _ref_bm25(
    tf: float, df: int, dl: int, avgdl: float, n_docs: int,
    k1: float = K1, b: float = B,
) -> float:
    """Reference BM25Okapi score for ONE query-token occurrence.

    idf(t)  = ln(1 + (N - df + 0.5) / (df + 0.5))          (Lucene-style)
    contrib = idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))

    Same formula as the spec / implementation, but re-derived here from
    first principles with hand-counted inputs.
    """
    idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
    return idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / avgdl))


# Corpus A — hand-counted statistics (no stopwords in any doc):
#   d1 "cat cat dog" -> tokens [cat, cat, dog]  dl=3
#   d2 "cat fish"    -> tokens [cat, fish]      dl=2
#   d3 "bird"        -> tokens [bird]           dl=1
# N=3, avgdl=(3+2+1)/3=2.0
# df: cat=2, dog=1, fish=1, bird=1
CORPUS_A = [("d1", "cat cat dog"), ("d2", "cat fish"), ("d3", "bird")]
N_A, AVGDL_A = 3, 2.0


def test_hand_verifiable_bm25():
    """3 tiny docs; expected scores recomputed via _ref_bm25 (hand-counted
    tf/df/dl/avgdl, formula re-derived from the spec — see module docstring)."""
    idx = LexicalIndex()
    assert idx.is_built is False
    idx.build(CORPUS_A)
    assert idx.is_built is True
    assert idx.doc_count == 3

    # "dog" hits only d1: tf=1, df=1, dl=3.
    exp_d1_dog = _ref_bm25(tf=1, df=1, dl=3, avgdl=AVGDL_A, n_docs=N_A)
    assert idx.query("dog") == [("d1", pytest.approx(exp_d1_dog))]

    # "cat" hits d1 (tf=2, dl=3) and d2 (tf=1, dl=2); d1 must outrank d2
    # (higher tf outweighs its longer dl with these k1/b).
    exp_d1_cat = _ref_bm25(tf=2, df=2, dl=3, avgdl=AVGDL_A, n_docs=N_A)
    exp_d2_cat = _ref_bm25(tf=1, df=2, dl=2, avgdl=AVGDL_A, n_docs=N_A)
    result = idx.query("cat")
    assert [cid for cid, _ in result] == ["d1", "d2"]
    assert result[0][1] == pytest.approx(exp_d1_cat)
    assert result[1][1] == pytest.approx(exp_d2_cat)
    assert result[0][1] > result[1][1]

    # Unknown tokens contribute 0 -> no hits at all.
    assert idx.query("zebra unicorn") == []


def test_idf_sanity_rare_vs_common():
    """A term present in ALL docs must score LOWER than a rare term for
    the same tf/dl — a pure idf effect (Lucene idf decreases in df)."""
    corpus = [
        ("x1", "apple banana"),
        ("x2", "apple cherry"),
        ("x3", "apple durian"),
    ]
    # All docs: dl=2, avgdl=2.0; df(apple)=3 (all docs), df(banana)=1.
    idx = LexicalIndex()
    idx.build(corpus)

    s_apple = dict(idx.query("apple"))["x1"]  # tf=1, df=3, dl=2
    s_banana = dict(idx.query("banana"))["x1"]  # tf=1, df=1, dl=2
    assert s_banana > s_apple

    # Same ordering visible in the reference numbers themselves:
    assert _ref_bm25(1, 1, 2, 2.0, 3) > _ref_bm25(1, 3, 2, 2.0, 3)
    # "apple" still matches every doc (downweighted, not banned):
    assert [cid for cid, _ in idx.query("apple")] == ["x1", "x2", "x3"]


def test_tokenize_cjk_bigrams():
    # Pure CJK run -> sliding character bigrams.
    assert tokenize("机器学习") == ["机器", "器学", "学习"]
    # Run of length 1 -> the single character.
    assert tokenize("机") == ["机"]
    # Mixed: the single word-char run "cnn报道机器学习" splits into the
    # ascii segment "cnn" (lowercased) + ONE contiguous CJK run
    # "报道机器学习" (报道 is CJK too) -> 5 sliding bigrams, including the
    # cross-word-boundary bigram 道机 (no word segmentation, by design).
    assert tokenize("CNN报道机器学习") == [
        "cnn", "报道", "道机", "机器", "器学", "学习",
    ]
    # Other bigram-eligible scripts: kana (U+3040-30FF) and hangul
    # (U+AC00-D7AF) — verified by codepoint in review.
    assert tokenize("こんにちは") == ["こん", "んに", "にち", "ちは"]
    assert tokenize("한국어") == ["한국", "국어"]
    # Accented latin stays one whole (western) token; case folded only.
    assert tokenize("Café RÉSUMÉ") == ["café", "résumé"]
    # Punctuation/whitespace split; digits are word chars.
    assert tokenize("cat, CAT! 42") == ["cat", "cat", "42"]
    # tokenize is PURE: stopwords are NOT filtered here (index-level only).
    assert tokenize("the cat") == ["the", "cat"]


def test_stopwords_default_and_disabled():
    # Default index drops ASCII stopwords from the token stream...
    idx = LexicalIndex()
    assert idx.tokens("The cat and the dog of it") == ["cat", "dog"]
    # ...while stopwords=None keeps everything ("the" survives).
    no_stops = LexicalIndex(stopwords=None)
    assert no_stops.tokens("The cat and the dog of it") == [
        "the", "cat", "and", "the", "dog", "of", "it",
    ]

    # Behavioural check through query(): "the" is indexed and matchable
    # only when stopwords are disabled.
    corpus = [("s1", "the cat")]  # default: tokens [cat], dl=1
    idx2 = LexicalIndex()
    idx2.build(corpus)
    assert idx2.query("the") == []
    assert idx2.query("the cat") == idx2.query("cat")

    idx3 = LexicalIndex(stopwords=None)
    idx3.build(corpus)  # tokens [the, cat], dl=2, avgdl=2, df=1 each
    hits = idx3.query("the")
    assert len(hits) == 1 and hits[0][0] == "s1"
    assert hits[0][1] == pytest.approx(
        _ref_bm25(tf=1, df=1, dl=2, avgdl=2.0, n_docs=1)
    )


def test_deterministic_tie_break():
    """Identical docs -> identical scores -> chunk_id ascending."""
    idx = LexicalIndex()
    idx.build([("zeta", "echo bravo"), ("alpha", "echo bravo")])
    result = idx.query("echo")
    assert [cid for cid, _ in result] == ["alpha", "zeta"]
    # Identical computation -> exactly equal floats.
    assert result[0][1] == result[1][1]


def test_rrf_fuse():
    # Consensus beats each list's own winner: "c" is rank-2 in BOTH lists
    # (1/62 + 1/62 = 1/31) vs "a"/"b" each rank-1 in only one list (1/61).
    # RRF changes the winner vs either input ranking.
    r1 = ["a", "c", "d"]
    r2 = ["b", "c", "e"]
    fused = rrf_fuse([r1, r2])
    assert fused[0] == "c"
    assert fused[0] != r1[0] and fused[0] != r2[0]
    # Full deterministic order: c, then a/b tie at 1/61 (id asc),
    # then d/e tie at 1/63 (id asc).
    assert fused == ["c", "a", "b", "d", "e"]

    # Ids missing from a list contribute 0 from that list
    # (a: 1/61, c: 1/61, b: 1/62 -> a/c tie, id asc, then b).
    assert rrf_fuse([["a", "b"], ["c"]]) == ["a", "c", "b"]

    # Empty rankings inside the input are tolerated.
    assert rrf_fuse([[], ["x"]]) == ["x"]
    assert rrf_fuse([["x"], []]) == ["x"]
    # All-empty / no input at all.
    assert rrf_fuse([[], []]) == []
    assert rrf_fuse([]) == []
    # Single ranking is an order-preserving passthrough.
    assert rrf_fuse([["p", "q", "r"]]) == ["p", "q", "r"]


def test_top_n_slicing():
    idx = LexicalIndex()
    idx.build(CORPUS_A)
    full = idx.query("cat")
    assert len(full) == 2
    assert idx.query("cat", top_n=1) == full[:1]
    assert idx.query("cat", top_n=5) == full  # larger than result count
    assert idx.query("cat", top_n=0) == []
    assert idx.query("cat", top_n=None) == full  # None = all


def test_empty_index_and_empty_docs():
    idx = LexicalIndex()
    assert idx.doc_count == 0
    assert idx.is_built is False
    assert idx.query("cat") == []  # never built

    idx.build([])  # built over an empty corpus
    assert idx.is_built is True
    assert idx.doc_count == 0
    assert idx.query("cat") == []

    idx.build([("e1", "!!! ... ---")])  # tokenizes to nothing
    assert idx.doc_count == 1
    assert idx.query("cat") == []  # avgdl == 0 guard, no ZeroDivision


def test_query_with_only_stopwords():
    idx = LexicalIndex()
    idx.build([("w1", "the cat of the dog")])  # indexed tokens: [cat, dog]
    assert idx.query("the of and to a") == []  # query side filters to []
    assert idx.query("the") == []
    # ...and a real term still works on the same index:
    assert dict(idx.query("cat"))["w1"] > 0.0


def test_repeated_query_tokens_sum_per_occurrence():
    """Standard Okapi: a query token repeated k times contributes k times."""
    idx = LexicalIndex()
    idx.build(CORPUS_A)
    once = dict(idx.query("cat"))
    twice = dict(idx.query("cat cat"))
    for cid, score in once.items():
        assert twice[cid] == pytest.approx(2.0 * score)
    # And matches the reference formula summed over two occurrences:
    assert twice["d1"] == pytest.approx(
        2.0 * _ref_bm25(tf=2, df=2, dl=3, avgdl=AVGDL_A, n_docs=N_A)
    )


def test_build_over_build_replaces_state():
    idx = LexicalIndex()
    idx.build(CORPUS_A)
    assert idx.doc_count == 3
    assert len(idx.query("cat")) == 2

    # Rebuild with a different corpus: old docs/terms must be GONE.
    idx.build([("n1", "dog"), ("n2", "fish")])
    assert idx.doc_count == 2
    assert idx.query("cat") == []  # no stale doc rows, no stale df hits
    # N=2, avgdl=1.0, df(dog)=1, tf=1, dl=1 -> hand-checkable:
    assert idx.query("dog") == [
        ("n1", pytest.approx(_ref_bm25(tf=1, df=1, dl=1, avgdl=1.0, n_docs=2)))
    ]

    # Rebuild back over corpus A: exact hand-verified numbers still hold
    # (proves no df/avgdl/idf state leaked from the previous build).
    idx.build(CORPUS_A)
    assert idx.query("dog") == [
        ("d1", pytest.approx(_ref_bm25(tf=1, df=1, dl=3, avgdl=AVGDL_A, n_docs=N_A)))
    ]
