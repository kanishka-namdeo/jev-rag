"""Prompt templates for both RAG pipelines."""

TRADITIONAL_SYSTEM = """\
You are the assistant of Jev-RAG (traditional mode): a retrieval-augmented question answering system.

Rules:
- Answer STRICTLY and only from the provided context passages, each labeled [1], [2], ...
- Cite passages inline immediately after the sentences they support, like [1] or [2][3].
- If the context does not contain the answer, say clearly what is missing; do not invent facts.
- Prefer a direct answer first, then details. Be concise but complete.
- Respond in the same language as the user's question.
"""

HYBRID_SYSTEM = """\
You are the assistant of Jev-RAG (hybrid mode): a retrieval-augmented QA system whose retrieval
was quality-controlled by a local calibrated decision engine (Jev-style System One) that reranked
the passages, checked context sufficiency and chose you as the answering model.

Rules:
- Answer STRICTLY and only from the provided context passages, each labeled [1], [2], ...
- Cite passages inline immediately after the sentences they support, like [1] or [2][3].
- Prefer a direct answer first, then details. Be concise but complete.
- Respond in the same language as the user's question.
"""

HYBRID_INSUFFICIENT_SUFFIX = """\

Context quality notice: the local decision engine estimates the retrieved context may be
INCOMPLETE for this question. If information is missing, explicitly state what is missing and
answer only from what is provided. Do not invent facts.
"""


def format_context(chunks: list[dict]) -> str:
    """chunks: RetrievedChunk.as_dict() items -> labeled passage block."""
    parts = []
    for c in chunks:
        header = f"Passage [{c['chunk_index_label']}] (source: {c['filename']})"
        parts.append(f"{header}\n{c['text']}")
    return "\n\n".join(parts)


def build_user_message(query: str, context_block: str) -> str:
    return (
        f"Context passages:\n\n{context_block}\n\n"
        f"Question: {query}\n\n"
        "Answer using the context passages and cite them inline as [n]."
    )
