from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingAdapter(ABC):
    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
