"""Local cross-encoder reranker (ONNX, CPU) for the v3 retrieval stack.

Why a cross-encoder instead of the local 0.5B LLM pointwise rerank
(`jev.rerank_chunks`): docs/rag-upgrade-2026.md §2.3 — a small cross-encoder
dominates a generative reranker on CPU per dollar (published comparison: Hit@1
62.67 -> 83.00% at ~150-170 ms for a 149M-278M cross-encoder), while LLM
pointwise reranking is the weakest and least reproducible LLM-rerank variant.
The chosen model, Xenova/ms-marco-MiniLM-L-6-v2, is a ~22M-parameter classic
ms-marco cross-encoder: its fp32 ONNX export is ~91 MB, so the whole thing
(tokenizer + weights + runtime) fits comfortably in the 4 GB CPU-only sandbox.
Scoring is fully deterministic given identical inputs (verified: identical
logits regardless of batch size / batch boundaries).

Model files (verified live via huggingface_hub.list_repo_files during task I3):
``onnx/model.onnx`` (fp32, ~91 MB) and ``tokenizer.json`` (~0.7 MB) — exactly
what ``load()`` downloads via snapshot_download(allow_patterns=["onnx/model.onnx",
"tokenizer.json"]). If a repo layout ever differs, the loader falls back to
``onnx/model_quantized.onnx`` before giving up. First use downloads ~91 MB from
the HF CDN (seconds-to-a-minute; egress verified in worklog); afterwards the
HF disk cache (~/.cache/huggingface by default, ``cache_dir`` to override)
makes loads instant. A repo-local ``models/`` dir exists for local artifacts;
wiring it as cache_dir happens at integration time (M4), default stays None.

Input contract (mirrors sentence-transformers CrossEncoder / transformers.js):
each (query, passage) pair is a two-segment BERT encode — [CLS] query [SEP]
passage [SEP] — with token_type_ids 0 for the query segment and 1 for the
passage segment. The pair Encoding supplies ids/attention_mask/type_ids
directly; we pass the real segment ids (NOT all-zeros — measured live: real
segments give 0.9996/0.0000 relevant-vs-irrelevant separation, all-zeros
collapses the relevant score to 0.76). Padding is done manually per batch
(BERT [PAD]=0 with attention_mask 0) because tokenizer-level padding is
disabled; truncation is tokenizer-level ``longest_first`` to max_length.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger("jevrag.crossenc")

DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

# Primary + fallback ONNX artifacts (see module docstring). Order matters:
# fp32 "model.onnx" is preferred; the quantized export is a layout fallback.
_ONNX_CANDIDATES = ["onnx/model.onnx", "onnx/model_quantized.onnx"]
_TOKENIZER_FILE = "tokenizer.json"
_PAD_ID = 0  # BERT [PAD]: pad ids/mask/type_ids all with 0


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid (logits here range ~[-12, +9])."""
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _pad_int64(rows: list[list[int]], width: int) -> np.ndarray:
    return np.array([r + [_PAD_ID] * (width - len(r)) for r in rows], dtype=np.int64)


class CrossEncoderReranker:
    """Thread-safe lazy ONNX cross-encoder producing P(relevant) per (query, passage).

    Lifecycle: construct cheaply (nothing loads), then ``load()`` once —
    idempotent, double-checked under a lock, never raises; failures are sticky
    in ``self._error`` (same contract as ``Embedder.load`` in rag/retriever.py).
    ``score_pairs``/``rerank`` return None / pass through until a successful
    load. Scoring itself is CPU-bound on a single InferenceSession: callers
    should serialize calls (the pipeline wraps this in ``asyncio.to_thread``).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        cache_dir: str | None = None,
        max_length: int = 512,
        threads: int | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.max_length = max_length
        self.threads = threads
        self._tokenizer = None          # tokenizers.Tokenizer (set on load)
        self._session = None            # ort.InferenceSession (set on load)
        self._error: str | None = None  # sticky failure description
        self._lock = threading.Lock()
        # Real ONNX input/output names, discovered from the loaded session
        # (exports may declare e.g. "token_type_ids" or omit it entirely).
        self._in_ids: str | None = None
        self._in_mask: str | None = None
        self._in_type: str | None = None
        self._out_name: str | None = None

    # -- loading -----------------------------------------------------------

    def load(self) -> bool:
        """Download (first run only) and initialize tokenizer + ONNX session.

        Idempotent: after success, repeated calls return True immediately with
        the same session object (no re-download). Never raises; on failure the
        error string is kept in ``self._error`` and False is returned (sticky —
        later calls fail fast without touching the network again).
        """
        if self._session is not None:
            return True
        with self._lock:
            if self._session is not None:
                return True
            if self._error is not None:
                return False
            try:
                self._load_locked()
                return True
            except Exception as e:  # noqa: BLE001 — contract: never raise
                self._error = f"{type(e).__name__}: {e}"
                logger.error(
                    "cross-encoder %s failed to load: %s", self.model_name, self._error
                )
                return False

    def _load_locked(self) -> None:
        from huggingface_hub import snapshot_download
        import onnxruntime as ort
        from tokenizers import Tokenizer

        # Resolve weights + tokenizer from the HF snapshot (disk-cached after
        # the first download). allow_patterns matching nothing is not an error,
        # so existence checks pick the first candidate that actually landed.
        onnx_path: Path | None = None
        tok_path: Path | None = None
        for pattern in _ONNX_CANDIDATES:
            local = Path(
                snapshot_download(
                    self.model_name,
                    allow_patterns=[pattern, _TOKENIZER_FILE],
                    cache_dir=self.cache_dir,
                )
            )
            cand, tcand = local / pattern, local / _TOKENIZER_FILE
            if cand.is_file() and tcand.is_file():
                onnx_path, tok_path = cand, tcand
                break
        if onnx_path is None or tok_path is None:
            raise FileNotFoundError(
                f"no ONNX weights + {_TOKENIZER_FILE} found for "
                f"{self.model_name} (tried {_ONNX_CANDIDATES})"
            )

        tokenizer = Tokenizer.from_file(str(tok_path))
        tokenizer.enable_truncation(max_length=self.max_length)  # longest_first
        tokenizer.no_padding()  # per-batch manual padding instead

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self.threads or min(4, os.cpu_count() or 1)
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL  # low RAM
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        # Prefer CUDA execution provider for GPU acceleration, fall back to CPU.
        # Query onnxruntime for actually-available providers: when the CUDA
        # provider is not installed (e.g. onnxruntime CPU wheel under WSL2,
        # where GPU passthrough is unavailable), passing it raises ValueError
        # ("Provider CUDAExecutionProvider is not available"), not the
        # RuntimeError the CUDA-init path raises.
        available = set(ort.get_available_providers())
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in available]
        if not providers:
            providers = ["CPUExecutionProvider"]
        if "CUDAExecutionProvider" in available:
            logger.info("CUDA execution provider available for cross-encoder")
        else:
            logger.info("CUDA execution provider not available, using CPU for cross-encoder")
        
        try:
            session = ort.InferenceSession(
                str(onnx_path), sess_options=opts, providers=providers
            )
        except (RuntimeError, ValueError) as e:
            # CUDA initialization failed (e.g., WSL2 GPU virtualization limitation)
            # Fall back to CPU-only
            if "CUDA" in str(e) or "cuda" in str(e):
                logger.warning("CUDA provider failed, falling back to CPU: %s", e)
                session = ort.InferenceSession(
                    str(onnx_path), sess_options=opts, providers=["CPUExecutionProvider"]
                )
            else:
                raise

        names = [i.name for i in session.get_inputs()]

        def _find(needle: str) -> str | None:
            return next((n for n in names if needle in n.lower()), None)

        in_ids, in_mask, in_type = (
            _find("input_ids"),
            _find("attention_mask"),
            _find("token_type_ids"),
        )
        if in_ids is None or in_mask is None:
            raise ValueError(
                f"unexpected ONNX inputs for {self.model_name}: {names}"
            )

        # Commit only after everything succeeded.
        self._tokenizer = tokenizer
        self._session = session
        self._in_ids, self._in_mask, self._in_type = in_ids, in_mask, in_type
        self._out_name = session.get_outputs()[0].name
        logger.info(
            "cross-encoder ready: %s (inputs=%s, threads=%d)",
            self.model_name, names, opts.intra_op_num_threads,
        )

    # -- scoring -----------------------------------------------------------

    def score_pairs(
        self, query: str, passages: list[str], batch_size: int = 8
    ) -> list[float] | None:
        """Sigmoid P(relevant) per (query, passage) pair, in input order.

        Returns [] for an empty passage list (degenerate input, no model
        needed) and None when the model is not loaded (caller checks /
        falls back). Raises only on genuine ONNX runtime errors — None is
        reserved for the not-loaded signal. Deterministic: batch size does
        not change the scores (padded positions carry attention_mask 0).
        """
        if not passages:
            return []
        if self._session is None or self._tokenizer is None:
            return None
        # Two-segment encode per pair == tokenizer.encode(query, passage),
        # batched: [CLS] query [SEP] passage [SEP] + segment type_ids 0/1.
        encodings = self._tokenizer.encode_batch([[query, p] for p in passages])
        scores: list[float] = []
        batch_size = max(1, int(batch_size))
        for start in range(0, len(encodings), batch_size):
            batch = encodings[start : start + batch_size]
            width = max(len(e.ids) for e in batch)
            feed = {
                self._in_ids: _pad_int64([e.ids for e in batch], width),
                self._in_mask: _pad_int64([e.attention_mask for e in batch], width),
            }
            if self._in_type is not None:
                feed[self._in_type] = _pad_int64([e.type_ids for e in batch], width)
            logits = self._session.run([self._out_name], feed)[0]
            # [B, 1] or [B] -> flat per-pair logit -> sigmoid
            scores.extend(_sigmoid(float(v)) for v in np.asarray(logits).reshape(-1))
        return scores

    def rerank(
        self,
        query: str,
        chunks: list[dict],
        text_key: str = "text",
        char_limit: int = 400,
    ) -> list[dict]:
        """Convenience: score chunk dicts and sort desc by new "ce_score" key.

        Mirrors the existing jev rerank char limit by truncating each chunk's
        text to ``char_limit`` characters before scoring. Returns shallow
        copies (dict(c)) of the SAME chunk dicts — originals are never
        mutated — sorted by ce_score (rounded to 4 decimals) descending,
        ties broken stably by original index. Empty chunks -> []. If the
        model is not loaded, chunks pass through unmodified in original
        order (graceful degradation — no ce_score key is added).
        """
        if not chunks:
            return []
        texts = [str(c.get(text_key, ""))[:char_limit] for c in chunks]
        scores = self.score_pairs(query, texts)
        if scores is None:
            return [dict(c) for c in chunks]
        decorated: list[tuple[int, dict]] = []
        for i, (chunk, score) in enumerate(zip(chunks, scores)):
            d = dict(chunk)
            d["ce_score"] = round(float(score), 4)
            decorated.append((i, d))
        decorated.sort(key=lambda t: (-t[1]["ce_score"], t[0]))
        return [d for _, d in decorated]

    def info(self) -> dict:
        """Status snapshot for /system/status-style consumers."""
        out = {
            "ok": self._session is not None,
            "model": self.model_name,
            "backend": "onnxruntime CPU",
            "loaded": self._session is not None,
        }
        if self._error is not None:
            out["error"] = self._error
        return out
