"""Pattern embedding helpers.

Patterns carry an optional 768-dim vector (matching the arXiv corpus embedding
model) used for similarity retrieval against ``ProblemProfile`` embeddings.

Embedding is best-effort: if the embeddings service is unavailable the
consolidation operator still persists rows; embedding can be backfilled later.
"""

from __future__ import annotations

import asyncio

from libs.adapters.embeddings.router import EmbeddingsRouter
from libs.core.logging import get_logger

log = get_logger("patterns.embedding")


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """Embed a list of texts; returns None entries if embedding fails."""
    if not texts:
        return []
    try:
        router = EmbeddingsRouter()
        try:
            vectors = asyncio.run(router.embed(texts))
        finally:
            asyncio.run(router.close())
        return [list(v) for v in vectors]
    except Exception as exc:
        log.warning("patterns.embedding_failed", error=str(exc), count=len(texts))
        return [None] * len(texts)


def embed_text(text: str) -> list[float] | None:
    """Embed a single text string for runtime pattern retrieval."""
    vectors = embed_texts([text])
    return vectors[0] if vectors else None


def pattern_text(title: str, summary: str) -> str:
    """Canonical text used for pattern embedding."""
    return f"{title}\n\n{summary}".strip()
