"""Tests for the reranker strategy fallback chain."""

from __future__ import annotations

import asyncio

from libs.adapters.reranker.base import (
    RerankBudgetExceeded,
    RerankDoc,
    Reranker,
    RerankerUnavailable,
    RerankResult,
)
from libs.adapters.reranker.no_op import NoOpReranker
from libs.discovery.rerank_strategy import run_rerank


class _AlwaysUnavailable(Reranker):
    name = "always_unavailable"

    async def rerank(self, query, docs, *, top_k=None, budget_seconds=None):
        raise RerankerUnavailable("model missing")

    async def health(self):
        return False


class _AlwaysOverBudget(Reranker):
    name = "always_over_budget"

    async def rerank(self, query, docs, *, top_k=None, budget_seconds=None):
        raise RerankBudgetExceeded("budget exhausted")

    async def health(self):
        return True


class _Working(Reranker):
    name = "working"

    async def rerank(self, query, docs, *, top_k=None, budget_seconds=None):
        return [
            RerankResult(id=doc.id, rerank_score=float(idx), rank=idx)
            for idx, doc in enumerate(docs)
        ]

    async def health(self):
        return True


def _docs() -> list[RerankDoc]:
    return [
        RerankDoc(id="a", text="alpha", first_stage_score=0.9),
        RerankDoc(id="b", text="beta", first_stage_score=0.5),
    ]


def test_rerank_disabled_uses_no_op_with_reason() -> None:
    outcome = asyncio.run(
        run_rerank(
            query="q",
            docs=_docs(),
            enabled=False,
            top_k=10,
            budget_seconds=30,
            primary=_Working(),
        )
    )
    assert outcome.used_reranker == "no_op"
    assert outcome.fallback_reason == "policy_disabled"
    # No-op preserves first-stage ordering
    assert [r.id for r in outcome.results] == ["a", "b"]


def test_rerank_falls_back_when_unavailable() -> None:
    outcome = asyncio.run(
        run_rerank(
            query="q",
            docs=_docs(),
            enabled=True,
            top_k=10,
            budget_seconds=30,
            primary=_AlwaysUnavailable(),
        )
    )
    assert outcome.used_reranker == "no_op"
    assert outcome.fallback_reason is not None
    assert "unavailable" in outcome.fallback_reason


def test_rerank_falls_back_on_budget_exhaustion() -> None:
    outcome = asyncio.run(
        run_rerank(
            query="q",
            docs=_docs(),
            enabled=True,
            top_k=10,
            budget_seconds=30,
            primary=_AlwaysOverBudget(),
        )
    )
    assert outcome.used_reranker == "no_op"
    assert outcome.fallback_reason is not None
    assert "budget_exceeded" in outcome.fallback_reason


def test_rerank_uses_primary_when_working() -> None:
    outcome = asyncio.run(
        run_rerank(
            query="q",
            docs=_docs(),
            enabled=True,
            top_k=10,
            budget_seconds=30,
            primary=_Working(),
        )
    )
    assert outcome.used_reranker == "working"
    assert outcome.fallback_reason is None


def test_no_op_reranker_handles_empty() -> None:
    outcome = asyncio.run(NoOpReranker().rerank("q", [], top_k=5))
    assert outcome == []
