"""Tests for stable / discovery view construction."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from uuid_utils import uuid7

from libs.discovery.views import build_discovery_view, build_stable_view
from libs.storage.models.papers import PaperCard


def _card(
    *,
    score: float,
    embedding: list[float] | None = None,
    categories: list[str] | None = None,
) -> PaperCard:
    return PaperCard(
        id=UUID(str(uuid7())),
        session_id=UUID(str(uuid7())),
        charter_id=UUID(str(uuid7())),
        source="internal_corpus",
        external_id=f"id-{score}",
        dedupe_key=f"k-{score}",
        title=f"paper-{score}",
        abstract="",
        authors=None,
        categories=categories,
        venue=None,
        year=None,
        published_at=None,
        doi=None,
        source_url=None,
        pdf_url=None,
        embedding=embedding,
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


def test_stable_view_picks_top_k_by_score() -> None:
    cards = [_card(score=s) for s in [0.1, 0.5, 0.9, 0.3]]
    out = build_stable_view(cards, top_k=2)
    scores = [c.final_score for c in out]
    assert scores == [0.9, 0.5]


def test_stable_view_is_deterministic_on_ties() -> None:
    cards = [_card(score=0.5) for _ in range(5)]
    out1 = build_stable_view(cards, top_k=3)
    out2 = build_stable_view(cards, top_k=3)
    assert [c.id for c in out1] == [c.id for c in out2]


def test_discovery_view_diversifies_with_categories() -> None:
    # Three high-relevance physics papers and two lower-relevance NLP papers.
    cards = [
        _card(score=0.95, categories=["physics.gen-ph"]),
        _card(score=0.94, categories=["physics.gen-ph"]),
        _card(score=0.93, categories=["physics.gen-ph"]),
        _card(score=0.6, categories=["cs.CL"]),
        _card(score=0.55, categories=["cs.CL"]),
    ]
    out = build_discovery_view(cards, top_k=3, lambda_param=0.5)
    cats = [c.categories[0] for c in out]
    # MMR should include at least one cs.CL paper despite lower relevance.
    assert "cs.CL" in cats


def test_discovery_view_falls_back_to_relevance_when_no_diversity_signal() -> None:
    cards = [_card(score=s) for s in [0.9, 0.8, 0.7, 0.6]]
    out = build_discovery_view(cards, top_k=2, lambda_param=0.7)
    assert out[0].final_score == 0.9


def test_discovery_view_handles_empty_input() -> None:
    assert build_discovery_view([], top_k=5) == []
