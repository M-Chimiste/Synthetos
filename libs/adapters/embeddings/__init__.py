"""Embedding adapter package."""

from libs.adapters.embeddings.base import EmbeddingAdapter
from libs.adapters.embeddings.openai_compat import OpenAICompatEmbeddingAdapter
from libs.adapters.embeddings.router import EXPECTED_DIMENSION, EmbeddingsRouter

__all__ = [
    "EXPECTED_DIMENSION",
    "EmbeddingAdapter",
    "EmbeddingsRouter",
    "OpenAICompatEmbeddingAdapter",
]
