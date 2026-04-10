"""Local cross-encoder reranker via sentence-transformers.

Lazily imports ``sentence_transformers`` so the rest of the system can run
without the optional dependency installed.  When the model is missing or the
import fails, :class:`LocalCrossEncoderReranker` raises
:class:`RerankerUnavailable` from :meth:`load`, and the strategy falls back
to :class:`NoOpReranker`.

The cross-encoder is run inside a thread executor (it is CPU/GPU-bound and
not async-aware) and respects a wall-clock budget; if scoring would exceed
``budget_seconds`` the call raises :class:`RerankBudgetExceeded` *before*
loading the model so callers can fall back without paying the load cost.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from libs.adapters.reranker.base import (
    RerankBudgetExceeded,
    RerankDoc,
    RerankerUnavailable,
    RerankResult,
)
from libs.core.logging import get_logger

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


_DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


class LocalCrossEncoderReranker:
    """Cross-encoder reranker backed by sentence-transformers."""

    name = "local_cross_encoder"

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: Any | None = None

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised via fallback test
            raise RerankerUnavailable(
                "sentence_transformers is not installed; "
                "install it to enable the local cross-encoder reranker"
            ) from exc

        try:
            self._model = CrossEncoder(self._model_name)
            log.info("local_cross_encoder.loaded", model=self._model_name)
        except Exception as exc:
            raise RerankerUnavailable(
                f"Failed to load cross-encoder '{self._model_name}': {exc}"
            ) from exc

    def _score(self, pairs: list[tuple[str, str]]) -> list[float]:
        assert self._model is not None
        scores = self._model.predict(pairs)
        return [float(s) for s in scores]

    async def rerank(
        self,
        query: str,
        docs: list[RerankDoc],
        *,
        top_k: int | None = None,
        budget_seconds: float | None = None,
    ) -> list[RerankResult]:
        if not docs:
            return []

        start = time.monotonic()
        if budget_seconds is not None and budget_seconds <= 0:
            raise RerankBudgetExceeded(
                f"rerank budget exhausted before scoring (budget={budget_seconds}s)"
            )

        try:
            self.load()
        except RerankerUnavailable:
            raise

        pairs = [(query, doc.text) for doc in docs]
        loop = asyncio.get_event_loop()
        try:
            if budget_seconds is not None:
                remaining = budget_seconds - (time.monotonic() - start)
                if remaining <= 0:
                    raise RerankBudgetExceeded("rerank budget exhausted before model.predict")
                scores = await asyncio.wait_for(
                    loop.run_in_executor(None, self._score, pairs),
                    timeout=remaining,
                )
            else:
                scores = await loop.run_in_executor(None, self._score, pairs)
        except TimeoutError as exc:
            raise RerankBudgetExceeded(
                f"cross-encoder.predict exceeded budget {budget_seconds}s"
            ) from exc

        scored = sorted(
            zip(docs, scores, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if top_k is not None:
            scored = scored[:top_k]

        return [
            RerankResult(id=doc.id, rerank_score=float(score), rank=idx)
            for idx, (doc, score) in enumerate(scored)
        ]

    async def health(self) -> bool:
        try:
            self.load()
        except RerankerUnavailable:
            return False
        return True
