from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingAdapter(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""

    def warmup(self) -> dict[str, str]:
        """Pre-load the model. Default is a no-op."""
        return {}

    def is_available(self) -> bool:
        """Check if the model is available locally. Default returns True."""
        return True
