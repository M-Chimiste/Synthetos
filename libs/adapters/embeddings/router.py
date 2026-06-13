"""Role-based embeddings router.

Mirrors :mod:`libs.adapters.llm.router` for embedding adapters. Reads the
``embeddings:`` section of ``configs/models.yaml`` and lazily constructs
the configured adapter.

Phase 1 only needs a single ``default`` profile, used both for query-time
embedding inside :class:`InternalCorpusAdapter` and for any future
re-embedding paths.

The configured embedding model **must** match the one used to populate
``arxiv_corpus.embedding`` -- mismatches will silently produce garbage
similarity scores.  The router validates the dimension at startup.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from libs.adapters.embeddings.base import EmbeddingAdapter
from libs.adapters.embeddings.openai_compat import OpenAICompatEmbeddingAdapter
from libs.adapters.embeddings.sentence_transformers import SentenceTransformersEmbeddingAdapter
from libs.core.config import get_settings
from libs.core.logging import get_logger

log = get_logger(__name__)


# Pinned to match the model used to embed the existing arXiv corpus.
EXPECTED_DIMENSION = 768


class EmbeddingsRouter:
    """Resolve and cache embedding adapters by named profile."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        if config_path is None:
            config_path = get_settings().model_config_path
        self._config_path = Path(config_path)
        self._config: dict[str, Any] = {}
        self._adapters: dict[str, EmbeddingAdapter] = {}
        self._load_config()

    def _load_config(self) -> None:
        if not self._config_path.exists():
            raise FileNotFoundError(f"Model config not found: {self._config_path}")

        with open(self._config_path) as f:
            self._config = yaml.safe_load(f) or {}

        embeddings = self._config.get("embeddings", {})
        log.info(
            "embeddings_router.config_loaded",
            path=str(self._config_path),
            profiles=list(embeddings.keys()),
        )

    def _get_profile(self, name: str) -> dict[str, Any]:
        embeddings = self._config.get("embeddings", {})
        if name not in embeddings:
            raise ValueError(
                f"No embeddings profile '{name}'. Available profiles: {list(embeddings.keys())}"
            )
        return dict(embeddings[name])

    def _build_adapter(self, profile: dict[str, Any]) -> EmbeddingAdapter:
        provider = profile.get("provider", "local")
        providers = self._config.get("providers", {})
        provider_cfg = dict(providers.get(provider, {}))
        provider_type = provider_cfg.get("type", provider)

        if provider_type == "sentence_transformers":
            model = profile.get("model")
            if not model:
                raise ValueError("embeddings profile is missing 'model'")
            dimensions = int(profile.get("dimension", EXPECTED_DIMENSION))
            return SentenceTransformersEmbeddingAdapter(
                model=model,
                dimensions=dimensions,
                batch_size=int(profile.get("batch_size", 64)),
                device=profile.get("device"),
                trust_remote_code=bool(profile.get("trust_remote_code", True)),
            )

        if provider_type not in {"openai_compatible", "openai", "local"}:
            raise ValueError(
                f"Embeddings provider '{provider}' (type={provider_type}) "
                "is not supported in Phase 1; expected OpenAI-compatible or sentence_transformers."
            )

        base_url = profile.get("base_url") or provider_cfg.get("base_url")
        if not base_url:
            raise ValueError(f"base_url required for embeddings profile (provider={provider})")

        model = profile.get("model")
        if not model:
            raise ValueError("embeddings profile is missing 'model'")

        dimensions = int(profile.get("dimension", EXPECTED_DIMENSION))
        if dimensions != EXPECTED_DIMENSION:
            log.warning(
                "embeddings_router.unexpected_dimension",
                configured=dimensions,
                expected=EXPECTED_DIMENSION,
            )

        return OpenAICompatEmbeddingAdapter(
            base_url=base_url,
            model=model,
            dimensions=dimensions,
            api_key=profile.get("api_key", "not-needed"),
        )

    def get(self, name: str = "default") -> EmbeddingAdapter:
        if name not in self._adapters:
            profile = self._get_profile(name)
            log.info(
                "embeddings_router.creating_adapter",
                profile=name,
                model=profile.get("model"),
            )
            self._adapters[name] = self._build_adapter(profile)
        return self._adapters[name]

    async def embed(self, texts: list[str], *, profile: str = "default") -> list[list[float]]:
        adapter = self.get(profile)
        return await adapter.embed(texts)

    async def close(self) -> None:
        for adapter in self._adapters.values():
            await adapter.close()
        self._adapters.clear()
