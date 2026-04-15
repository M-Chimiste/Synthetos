"""Tests for the discovery evaluation metrics."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from uuid_utils import uuid7

from libs.discovery.evaluation import mrr, precision_at_k, recall_at_k
from libs.storage.models.papers import PaperCard


def _card(external_id: str, score: float) -> PaperCard:
    return PaperCard(
        id=UUID(str(uuid7())),
        session_id=UUID(str(uuid7())),
        charter_id=UUID(str(uuid7())),
        source="internal_corpus",
        external_id=external_id,
        dedupe_key=external_id,
        title=external_id,
        abstract="",
        authors=None,
        categories=None,
        venue=None,
        year=None,
        published_at=None,
        doi=None,
        source_url=None,
        pdf_url=None,
        embedding=None,
        bm25_score=None,
        dense_score=None,
        first_stage_score=score,
        rerank_score=None,
        final_score=score,
        view_membership=None,
        triage_status="discovered",
        triage_reason=None,
        metadata_analysis=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_recall_at_k_counts_hits_within_top_k() -> None:
    ranked = [_card(f"p{i}", 1.0 - i / 10) for i in range(10)]
    relevant = {"p0", "p3", "p9"}
    assert recall_at_k(ranked, relevant, k=5) == 2 / 3  # p0 and p3 within top 5
    assert recall_at_k(ranked, relevant, k=10) == 1.0


def test_precision_at_k_returns_fraction_relevant() -> None:
    ranked = [_card(f"p{i}", 1.0 - i / 10) for i in range(5)]
    relevant = {"p0", "p1"}
    assert precision_at_k(ranked, relevant, k=2) == 1.0
    assert precision_at_k(ranked, relevant, k=5) == 2 / 5


def test_mrr_returns_reciprocal_of_first_hit() -> None:
    ranked = [_card("a", 1.0), _card("b", 0.9), _card("c", 0.8)]
    assert mrr(ranked, {"c"}) == 1 / 3
    assert mrr(ranked, {"a", "c"}) == 1.0
    assert mrr(ranked, {"missing"}) == 0.0
