from __future__ import annotations

from collections.abc import Sequence

import structlog

from libs.adapters.embeddings.base import EmbeddingAdapter
from libs.core.config import EmbeddingConfig

log = structlog.get_logger(__name__)


class SentenceTransformerEmbeddingAdapter(EmbeddingAdapter):
    """Local sentence-transformers embedding adapter."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - dependency error path
                raise RuntimeError(
                    "sentence-transformers is required for semantic search. "
                    "Run `uv sync` to install project dependencies."
                ) from exc
            if not self.is_available():
                log.warning(
                    "embedding_model_downloading",
                    model_id=self.config.model_id,
                    message="Model not cached locally; downloading from HuggingFace",
                )
            self._model = SentenceTransformer(
                self.config.model_id,
                device=self.config.device,
            )
        return self._model

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(
            list(texts),
            batch_size=self.config.batch_size,
            normalize_embeddings=self.config.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [vector.astype(float).tolist() for vector in vectors]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        vectors = self._encode([text])
        return vectors[0] if vectors else []

    def warmup(self) -> dict[str, str]:
        """Pre-load the embedding model, downloading if needed."""
        log.info("embedding_model_warmup_start", model_id=self.config.model_id)
        self._get_model()
        log.info("embedding_model_warmup_complete", model_id=self.config.model_id)
        return {"model_id": self.config.model_id, "device": self.config.device}

    def is_available(self) -> bool:
        """Check if the model is already cached locally."""
        try:
            from huggingface_hub import try_to_load_from_cache

            result = try_to_load_from_cache(self.config.model_id, "config.json")
            return result is not None
        except Exception:
            return False
