"""No-op reranker -- returns inputs unchanged.

Used as a graceful fallback when:
  * the cross-encoder model is missing or fails to load,
  * the reranker raises :class:`RerankBudgetExceeded`,
  * the cycle's :class:`RerankPolicy` has ``enabled = False``.

Each fallback emits a ``discovery.rerank_skipped`` event upstream so the
operator log records *why* the rerank step was skipped.
"""

from __future__ import annotations

from libs.adapters.reranker.base import RerankDoc, RerankResult


class NoOpReranker:
    """Pass-through reranker that copies the first-stage ordering."""

    name = "no_op"

    async def rerank(
        self,
        query: str,
        docs: list[RerankDoc],
        *,
        top_k: int | None = None,
        budget_seconds: float | None = None,
    ) -> list[RerankResult]:
        # Sort by first_stage_score so we expose a stable ordering even
        # when the input list isn't pre-sorted.
        ordered = sorted(
            docs,
            key=lambda d: (d.first_stage_score or 0.0),
            reverse=True,
        )
        if top_k is not None:
            ordered = ordered[:top_k]
        return [
            RerankResult(
                id=doc.id,
                rerank_score=doc.first_stage_score or 0.0,
                rank=idx,
            )
            for idx, doc in enumerate(ordered)
        ]

    async def health(self) -> bool:
        return True
