"""Base protocol for embedding adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Protocol that all embedding adapters must satisfy."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for a list of texts."""
        ...

    async def embed_batch(self, texts: list[str], *, batch_size: int = 64) -> list[list[float]]:
        """Compute embeddings in batches, returning all results concatenated."""
        ...

    async def close(self) -> None:
        """Release adapter resources."""
        ...
