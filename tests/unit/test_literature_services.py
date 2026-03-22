"""Unit tests for libs.literature.services."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.adapters.literature import RawPaperRecord
from libs.core.ids import generate_public_id
from libs.literature.services import (
    build_escalation_reason,
    build_screening_report_markdown,
    compute_shortlist,
    get_escalation_candidates,
    get_papers_for_screening,
    ingest_papers,
    record_screening_decision,
    retrieval_provenance_summary,
    select_escalation_candidates,
)
from libs.storage.base import Base
from libs.storage.models import (
    ResearchCharterModel,
    ResearchCycleModel,
    SourceRetrievalSessionModel,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def cycle(db_session: Session):
    charter = ResearchCharterModel(
        public_id=generate_public_id("charter"),
        title="Test Charter",
        problem_statement="Test problem",
        success_criteria={},
        budget_envelope={},
        source_scope={},
        stop_conditions={},
        constraints={},
    )
    db_session.add(charter)
    db_session.flush()
    cycle = ResearchCycleModel(
        public_id=generate_public_id("cycle"),
        charter_id=charter.id,
        current_status="ready",
    )
    db_session.add(cycle)
    db_session.flush()
    return cycle


@pytest.fixture()
def retrieval_session(db_session: Session, cycle: ResearchCycleModel):
    session = SourceRetrievalSessionModel(
        public_id=generate_public_id("retsess"),
        cycle_id=cycle.id,
        source_type="arxiv_metadata",
        query_params={},
        status="running",
    )
    db_session.add(session)
    db_session.flush()
    return session


def _make_raw_papers() -> list[RawPaperRecord]:
    return [
        RawPaperRecord(
            external_id="2401.00001",
            title="Paper Alpha",
            abstract="Good abstract about ML.",
            authors=["Alice"],
            categories=["cs.LG"],
            source_type="arxiv",
        ),
        RawPaperRecord(
            external_id="2401.00002",
            title="Paper Beta",
            abstract="Another ML paper.",
            authors=["Bob"],
            categories=["cs.LG"],
            source_type="arxiv",
        ),
    ]


def test_ingest_papers_deduplicates(db_session, cycle, retrieval_session):
    raw = _make_raw_papers()
    first = ingest_papers(db_session, cycle, retrieval_session, raw)
    assert len(first) == 2
    # Ingest the same papers again — should be deduplicated
    second = ingest_papers(db_session, cycle, retrieval_session, raw)
    assert len(second) == 0


def test_ingest_papers_merges_cross_source_duplicates(db_session, cycle, retrieval_session):
    arxiv_raw = RawPaperRecord(
        external_id="2401.00001",
        title="Paper Alpha",
        abstract="Good abstract about ML.",
        authors=["Alice"],
        categories=["cs.LG"],
        publication_date="2024-01-01",
        source_type="arxiv",
        metadata_extra={"doi": "10.1000/example"},
    )
    corpus_raw = RawPaperRecord(
        external_id="corpus:alpha",
        title="Paper Alpha",
        abstract="Local notes about the same paper.",
        authors=[],
        categories=["internal"],
        publication_date="2024-01-15",
        source_type="internal_corpus",
    )

    first = ingest_papers(db_session, cycle, retrieval_session, [arxiv_raw])
    second = ingest_papers(db_session, cycle, retrieval_session, [corpus_raw])

    assert len(first) == 1
    assert len(second) == 0
    provenance = retrieval_provenance_summary(first[0].metadata_extra)
    assert "arxiv: 2401.00001" in provenance
    assert "internal_corpus: corpus:alpha" in provenance


def test_record_screening_decision_updates_lifecycle(db_session, cycle, retrieval_session):
    raw = _make_raw_papers()
    papers = ingest_papers(db_session, cycle, retrieval_session, raw)
    paper = papers[0]
    assert paper.lifecycle_status == "retrieved"

    record_screening_decision(
        db_session, paper,
        decision="advance", score=0.85,
        rationale="Highly relevant",
        model_route_id="triage-default",
        prompt_id="test_prompt",
        batch_index=0,
    )
    assert paper.lifecycle_status == "screened"
    assert paper.triage_score == 0.85


def test_compute_shortlist_ranks_by_score(db_session, cycle, retrieval_session):
    raw = _make_raw_papers()
    papers = ingest_papers(db_session, cycle, retrieval_session, raw)

    # Screen papers with different scores
    record_screening_decision(
        db_session, papers[0], decision="advance", score=0.7,
        rationale="OK", model_route_id="t", prompt_id="p", batch_index=0,
    )
    record_screening_decision(
        db_session, papers[1], decision="advance", score=0.9,
        rationale="Great", model_route_id="t", prompt_id="p", batch_index=0,
    )

    shortlisted = compute_shortlist(db_session, cycle.id, max_shortlist=10)
    assert len(shortlisted) == 2
    # Higher score should be rank 1
    assert shortlisted[0].triage_score == 0.9
    assert shortlisted[0].shortlist_rank == 1
    assert shortlisted[1].shortlist_rank == 2


def test_get_escalation_candidates(db_session, cycle, retrieval_session):
    raw = _make_raw_papers()
    papers = ingest_papers(db_session, cycle, retrieval_session, raw)
    for p in papers:
        record_screening_decision(
            db_session, p, decision="advance", score=0.8,
            rationale="Good", model_route_id="t", prompt_id="p", batch_index=0,
        )
    compute_shortlist(db_session, cycle.id)

    candidates = get_escalation_candidates(db_session, cycle.id)
    assert len(candidates) == 2
    assert all(c.fulltext_artifact_path is None for c in candidates)


def test_select_escalation_candidates_respects_budget(db_session, cycle, retrieval_session):
    raw = _make_raw_papers()
    papers = ingest_papers(db_session, cycle, retrieval_session, raw)
    for p in papers:
        record_screening_decision(
            db_session, p, decision="advance", score=0.8,
            rationale="Good", model_route_id="t", prompt_id="p", batch_index=0,
        )
    shortlisted = compute_shortlist(db_session, cycle.id)

    selected, skipped = select_escalation_candidates(db_session, cycle.id, max_fetches=1)
    assert len(shortlisted) == 2
    assert len(selected) == 1
    assert skipped == 1
    assert build_escalation_reason(selected[0]).startswith("Escalated for deeper read")


def test_get_papers_for_screening(db_session, cycle, retrieval_session):
    raw = _make_raw_papers()
    ingest_papers(db_session, cycle, retrieval_session, raw)
    batch = get_papers_for_screening(db_session, cycle.id, batch_size=1)
    assert len(batch) == 1


def test_build_screening_report_markdown(db_session, cycle, retrieval_session):
    raw = _make_raw_papers()
    papers = ingest_papers(db_session, cycle, retrieval_session, raw)
    for p in papers:
        record_screening_decision(
            db_session, p, decision="advance", score=0.8,
            rationale="Good", model_route_id="t", prompt_id="p", batch_index=0,
        )
    compute_shortlist(db_session, cycle.id)

    md = build_screening_report_markdown(db_session, cycle, "Test Charter")
    assert "Literature Screening Report" in md
    assert "Paper Alpha" in md or "Paper Beta" in md
    assert "Shortlisted Papers" in md
