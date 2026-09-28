"""Lexical (BM25) retrieval + RRF fusion — the sparse half of hybrid retrieval.

Purpose
-------
Implements the lexical stage of the 2026-standard hybrid retrieval stack:
BM25 ‖ dense-embedding retrieval fused with Reciprocal Rank Fusion (RRF).
BM25 rescues exactly this project's measured failure profile — exact entity
and lexical lookups (2WikiMultiHopQA / TriviaQA style) that a multilingual
MiniLM dense index ranks poorly — while RRF fuses the two ranked lists
without needing comparable score scales. Hybrid lexical+dense + RRF is the
settled default in current production RAG systems.

Design constraints (why this file looks like 1998)
--------------------------------------------------
* ZERO third-party dependencies, by design: pure stdlib (``re``, ``math``,
  ``collections``). Sandbox pip egress is unreliable, so the lexical path
  must never require a network install (no rank_bm25, no jieba, no mecab).
* The index is rebuilt in memory from Chroma collection contents
  (``chunk_id -> text``); there is deliberately NO persistence format, no
  incremental update protocol and no on-disk state. Rebuild is O(corpus)
  and cheap (1500 chunks x ~900 chars builds in well under 2s pure python),
  so "rebuild from the source of truth" is the whole storage story.
* Determinism: :func:`tokenize` is a pure function; query/rrf results are
  sorted by score desc then chunk_id asc, so output is stable across runs
  and platforms.

Public API
----------
- :func:`tokenize` — pure tokenizer (lowercase, western words, CJK bigrams;
  no stopword filtering — that lives on :class:`LexicalIndex`).
- :class:`LexicalIndex` — BM25Okapi index (Lucene-style idf).
- :func:`rrf_fuse` — reciprocal-rank fusion of ordered id lists.
"""
from __future__ import annotations

import math
import re
from collections import Counter

__all__ = ["LexicalIndex", "rrf_fuse", "tokenize"]

# --------------------------------------------------------------------------
# Tokenization
# --------------------------------------------------------------------------

#: Tiny English stopword list. Applied ONLY to ASCII alphabetic tokens
#: (never to CJK bigrams, digits or mixed tokens). Pass ``None`` to disable.
_DEFAULT_STOP: frozenset[str] = frozenset(
    {
        "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is",
        "are", "was", "were", "be", "been", "it", "its", "as", "at", "by",
        "with", "from", "that", "this",
    }
)

# Word characters: ASCII alnum + underscore + U+00C0..U+FFFF (covers
# accented latin, greek, cyrillic, CJK ideographs/kana/hangul, ...).
# Written with \\u escapes to keep the source ASCII-safe.
_WORD_RE = re.compile(r"[0-9A-Za-z_\u00c0-\uffff]+")

# Script ranges that get character-bigram tokenization instead of whole
# "words" (no spaces, and single characters are too sparse to match on).
_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs (han)
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0xAC00, 0xD7AF),  # Hangul syllables
)


def _is_cjk(ch: str) -> bool:
    """True if *ch* falls in one of the bigram-eligible CJK ranges."""
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _cjk_bigrams(segment: str) -> list[str]:
    """Sliding character bigrams of a contiguous CJK run.

    A run of length 1 yields the single character (nothing to pair).
    Runs are NOT word-segmented: "机器学习" -> ["机器", "器学", "学习"].
    """
    if len(segment) == 1:
        return [segment]
    return [segment[i : i + 2] for i in range(len(segment) - 1)]


def tokenize(text: str) -> list[str]:
    """Pure, deterministic tokenizer. No stopwords, no state.

    Rules:
    1. Lowercase the input.
    2. Find runs of word characters (``[0-9A-Za-z_\\u00c0-\\uffff]+`` —
       western words incl. accented, digits, underscore).
    3. Within a run, contiguous CJK subsequences (han U+4E00–U+9FFF,
       kana U+3040–U+30FF, hangul U+AC00–U+D7AF) become character
       BIGRAMS ("机器学习" -> ["机器", "器学", "学习"]; a lone char stays
       single). Non-CJK segments stay whole tokens, so mixed text like
       "CNN报道机器学习" -> ["cnn", "报道", "道机", "机器", "器学", "学习"].
    4. Stopword filtering is NOT applied here — it is an index-level
       concern (see :class:`LexicalIndex` ``stopwords`` parameter).
    """
    tokens: list[str] = []
    for run in _WORD_RE.findall(text.lower()):
        if not run:  # defensive; "+" cannot match empty
            continue
        start = 0
        cur_cjk = _is_cjk(run[0])
        for i in range(1, len(run)):
            if _is_cjk(run[i]) != cur_cjk:  # script boundary inside run
                segment = run[start:i]
                if cur_cjk:
                    tokens.extend(_cjk_bigrams(segment))
                else:
                    tokens.append(segment)
                start = i
                cur_cjk = not cur_cjk
        segment = run[start:]  # trailing segment
        if cur_cjk:
            tokens.extend(_cjk_bigrams(segment))
        else:
            tokens.append(segment)
    return tokens


# --------------------------------------------------------------------------
# BM25 index
# --------------------------------------------------------------------------


class LexicalIndex:
    """In-memory BM25Okapi index over ``(chunk_id, text)`` pairs.

    Scoring is standard Okapi BM25 with Lucene-style idf::

        idf(t)      = ln(1 + (N - df + 0.5) / (df + 0.5))
        score(q, d) = sum over each query-token OCCURRENCE t of
                      idf(t) * (tf * (k1 + 1)) /
                      (tf + k1 * (1 - b + b * dl / avgdl))

    * Unknown terms (not in the index vocabulary) contribute 0.
    * A query term repeated k times contributes k times (simple loop over
      the query token list — standard Okapi behaviour).
    * :meth:`query` returns only documents with a positive score, sorted
      by score descending, then chunk_id ascending (deterministic).
    * ``build()`` fully replaces any prior state (safe to rebuild in place).

    Thread-safety: ``build()``/``query()`` are NOT locked. Callers must
    serialize access themselves — production code invokes this class via
    ``asyncio.to_thread`` with a single owning task, so no internal locking
    is added (keeps the hot path lock-free and the contract explicit).

    Performance: ``build()`` for 1500 docs x ~900 chars completes well
    under 2s in pure CPython; a query is O(query tokens x N docs).
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        stopwords: frozenset[str] | None = _DEFAULT_STOP,
    ) -> None:
        self.k1 = float(k1)
        self.b = float(b)
        self.stopwords: frozenset[str] | None = (
            frozenset(stopwords) if stopwords is not None else None
        )
        self._doc_ids: list[str] = []
        self._tfs: list[dict[str, int]] = []
        self._doc_lens: list[int] = []
        self._df: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._avgdl: float = 0.0
        self._built: bool = False

    # -- introspection ------------------------------------------------------

    @property
    def doc_count(self) -> int:
        """Number of documents in the currently built index."""
        return len(self._doc_ids)

    @property
    def is_built(self) -> bool:
        """True once ``build()`` has run (even over an empty corpus)."""
        return self._built

    # -- tokenization with index-level stopwords ----------------------------

    def tokens(self, text: str) -> list[str]:
        """``tokenize(text)`` with this index's stopword filter applied.

        This is the exact token stream ``build``/``query`` see; exposed so
        callers and tests can inspect tokenization behaviour (stopwords are
        dropped only for ASCII alphabetic tokens).
        """
        toks = tokenize(text)
        sw = self.stopwords
        if sw is None:
            return toks
        return [t for t in toks if not (t.isascii() and t.isalpha() and t in sw)]

    # -- build / query -------------------------------------------------------

    def build(self, corpus: list[tuple[str, str]]) -> None:
        """(Re)build the index from ``corpus`` items ``(chunk_id, text)``.

        Replaces any prior state completely. O(corpus) time, O(vocabulary)
        memory. Safe to call repeatedly (e.g. lazy rebuild after ingest).
        Assumes chunk_ids are unique within one corpus.
        """
        # Reset ALL state first so a rebuild never leaks stale statistics.
        self._doc_ids = []
        self._tfs = []
        self._doc_lens = []
        self._df = {}
        self._idf = {}
        self._avgdl = 0.0
        self._built = True

        df: dict[str, int] = {}
        for chunk_id, text in corpus:
            self._doc_ids.append(chunk_id)
            tf: dict[str, int] = Counter(self.tokens(text))
            self._tfs.append(tf)
            dl = sum(tf.values())
            self._doc_lens.append(dl)
            for term in tf:
                df[term] = df.get(term, 0) + 1

        n = len(self._doc_ids)
        self._df = df
        self._avgdl = (sum(self._doc_lens) / n) if n else 0.0
        # Lucene-style idf, precomputed once per term.
        self._idf = {
            term: math.log(1.0 + (n - d + 0.5) / (d + 0.5))
            for term, d in df.items()
        }

    def query(self, text: str, top_n: int | None = None) -> list[tuple[str, float]]:
        """Score ``text`` against the index; return ``(chunk_id, score)``.

        Sorted by score descending, then chunk_id ascending. Only documents
        with a positive score are returned (zero-score / non-matching docs
        are dropped, matching Lucene behaviour). ``top_n=None`` returns all
        hits; an integer slices the sorted list. Querying an empty or
        all-empty-doc index returns ``[]``.
        """
        n = len(self._doc_ids)
        if n == 0 or self._avgdl <= 0.0:
            return []
        q_tokens = self.tokens(text)
        if not q_tokens:
            return []

        k1, b, avgdl = self.k1, self.b, self._avgdl
        scores = [0.0] * n
        # One pass per query-token OCCURRENCE (standard Okapi): a token
        # repeated in the query contributes once per repetition.
        for tok in q_tokens:
            idf = self._idf.get(tok)
            if idf is None:  # unknown token contributes 0
                continue
            for i in range(n):
                tf = self._tfs[i].get(tok)
                if not tf:
                    continue
                dl = self._doc_lens[i]
                scores[i] += (
                    idf
                    * (tf * (k1 + 1.0))
                    / (tf + k1 * (1.0 - b + b * dl / avgdl))
                )

        hits = [
            (self._doc_ids[i], s) for i, s in enumerate(scores) if s > 0.0
        ]
        hits.sort(key=lambda pair: (-pair[1], pair[0]))
        if top_n is not None:
            hits = hits[:top_n]
        return hits


# --------------------------------------------------------------------------
# Reciprocal Rank Fusion
# --------------------------------------------------------------------------


def rrf_fuse(rankings: list[list[str]], rrf_k: int = 60) -> list[str]:
    """Fuse multiple ranked chunk_id lists with Reciprocal Rank Fusion.

    Each ranking is an ordered list of chunk_ids (best first, ids assumed
    unique within one list). Fused score of an id::

        sum over rankings containing it of 1 / (rrf_k + rank)   (rank >= 1)

    Ids missing from a ranking contribute 0 from that ranking. Output is
    sorted by fused score descending, then id ascending (deterministic).
    Empty input (or only empty rankings) yields ``[]``.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [chunk_id for chunk_id, _ in ordered]
