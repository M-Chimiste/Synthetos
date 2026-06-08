"""SentenceTransformers embedding adapter for local query/chunk embeddings."""

from __future__ import annotations

from typing import Any

from libs.core.logging import get_logger

log = get_logger(__name__)


class SentenceTransformersEmbeddingAdapter:
    """Embedding adapter backed by ``sentence-transformers``.

    This is useful on workstations that have the corpus embedding model cached
    locally but do not run a separate OpenAI-compatible embedding server.
    """

    def __init__(
        self,
        *,
        model: str,
        dimensions: int = 768,
        batch_size: int = 64,
        device: str | None = None,
        trust_remote_code: bool = True,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. Run with `uv run --extra reranker ...`."
            ) from exc

        kwargs: dict[str, Any] = {
            "trust_remote_code": trust_remote_code,
            "config_kwargs": {"reference_compile": False},
            "model_kwargs": {"attn_implementation": "sdpa"},
        }
        if device:
            kwargs["device"] = device

        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._model = SentenceTransformer(model, **kwargs)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_batch(texts, batch_size=self.batch_size)

    async def embed_batch(self, texts: list[str], *, batch_size: int = 64) -> list[list[float]]:
        if not texts:
            return []

        log.debug("sentence_transformers.embed_batch", model=self.model, num_texts=len(texts))
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = [[float(value) for value in embedding] for embedding in embeddings]
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise RuntimeError(
                    f"Embedding dimension {len(vector)} did not match expected {self.dimensions}"
                )
        return vectors

    async def close(self) -> None:
        return None
