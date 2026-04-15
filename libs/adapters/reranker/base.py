"""Reranker protocol and shared DTOs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RerankDoc(BaseModel):
    """Input document for reranking."""

    id: str
    text: str
    first_stage_score: float | None = None


class RerankResult(BaseModel):
    """One scored document from the reranker."""

    id: str
    rerank_score: float
    rank: int = Field(ge=0)


class RerankerError(Exception):
    """Base reranker error."""


class RerankerUnavailable(RerankerError):
    """Raised when the reranker model cannot be loaded or contacted."""


class RerankBudgetExceeded(RerankerError):
    """Raised when reranking would exceed the configured wall-clock budget."""


@runtime_checkable
class Reranker(Protocol):
    """Protocol that all reranker adapters must satisfy."""

    name: str

    async def rerank(
        self,
        query: str,
        docs: list[RerankDoc],
        *,
        top_k: int | None = None,
        budget_seconds: float | None = None,
    ) -> list[RerankResult]:
        """Score and rank ``docs`` against ``query``."""
        ...

    async def health(self) -> bool:
        """Quick check that the reranker is loadable / reachable."""
        ...
