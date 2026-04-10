"""Reranker selection and graceful-fallback chain."""

from __future__ import annotations

from dataclasses import dataclass

from libs.adapters.reranker.base import (
    RerankBudgetExceeded,
    RerankDoc,
    Reranker,
    RerankerError,
    RerankerUnavailable,
    RerankResult,
)
from libs.adapters.reranker.local_cross_encoder import LocalCrossEncoderReranker
from libs.adapters.reranker.no_op import NoOpReranker
from libs.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class RerankOutcome:
    """Result of running the rerank strategy."""

    results: list[RerankResult]
    used_reranker: str
    fallback_reason: str | None = None


def build_default_reranker(model_name: str | None = None) -> Reranker:
    """Construct the configured local cross-encoder."""
    if model_name:
        return LocalCrossEncoderReranker(model_name=model_name)
    return LocalCrossEncoderReranker()


async def run_rerank(
    *,
    query: str,
    docs: list[RerankDoc],
    enabled: bool,
    top_k: int,
    budget_seconds: float,
    primary: Reranker | None = None,
) -> RerankOutcome:
    """Run the rerank step with graceful fallback to a no-op reranker.

    Fallback paths (every one emits a ``discovery.rerank_skipped`` event upstream):

    1. ``enabled = False`` -- skip the rerank entirely.
    2. cross-encoder cannot be loaded -- :class:`RerankerUnavailable`.
    3. cross-encoder times out / overruns the wall-clock budget --
       :class:`RerankBudgetExceeded`.

    The no-op reranker simply preserves first-stage ordering.
    """
    no_op = NoOpReranker()

    if not enabled:
        results = await no_op.rerank(query, docs, top_k=top_k)
        return RerankOutcome(
            results=results,
            used_reranker="no_op",
            fallback_reason="policy_disabled",
        )

    reranker = primary or build_default_reranker()
    try:
        results = await reranker.rerank(
            query,
            docs,
            top_k=top_k,
            budget_seconds=budget_seconds,
        )
        return RerankOutcome(results=results, used_reranker=reranker.name)
    except RerankerUnavailable as exc:
        log.warning("rerank_strategy.unavailable", error=str(exc))
        results = await no_op.rerank(query, docs, top_k=top_k)
        return RerankOutcome(
            results=results,
            used_reranker="no_op",
            fallback_reason=f"unavailable:{exc}",
        )
    except RerankBudgetExceeded as exc:
        log.warning("rerank_strategy.budget_exceeded", error=str(exc))
        results = await no_op.rerank(query, docs, top_k=top_k)
        return RerankOutcome(
            results=results,
            used_reranker="no_op",
            fallback_reason=f"budget_exceeded:{exc}",
        )
    except RerankerError as exc:
        log.warning("rerank_strategy.generic_error", error=str(exc))
        results = await no_op.rerank(query, docs, top_k=top_k)
        return RerankOutcome(
            results=results,
            used_reranker="no_op",
            fallback_reason=f"error:{exc}",
        )
