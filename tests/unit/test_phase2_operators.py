"""Unit tests for Phase 2 operator gating behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.core.config import AppConfig
from libs.core.ids import generate_public_id
from libs.core.policy import SYSTEM_ACTOR
from libs.orchestration.operators import (
    evidence_extraction_operator,
    hypothesis_critique_operator,
    hypothesis_generation_operator,
    protocol_compilation_operator,
)
from libs.storage import services
from libs.storage.base import Base
from libs.storage.models import (
    JobModel,
    PaperCardModel,
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
def config(tmp_path) -> AppConfig:
    cfg = AppConfig(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_root=tmp_path / "data",
        model_config_path=Path("configs/models/routes.yaml"),
        policy_config_path=Path("configs/policies/default.yaml"),
        skill_paths=[Path("skills")],
        auto_init_db=False,
    )
    cfg.ensure_data_dirs()
    return cfg


@pytest.fixture()
def cycle(db_session: Session):
    charter = ResearchCharterModel(
        public_id=generate_public_id("charter"),
        title="Phase 2 Operator Test",
        problem_statement="Test evidence-first gating",
        success_criteria={"summary": "Generate protocol"},
        budget_envelope={},
        source_scope={},
        stop_conditions={"summary": "Stop after phase 2"},
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


def _create_job(
    db_session: Session,
    cycle: ResearchCycleModel,
    operator_name: str,
) -> JobModel:
    job = JobModel(
        public_id=generate_public_id("job"),
        cycle_id=cycle.id,
        operator_name=operator_name,
        status="pending",
        payload={"cycle_public_id": cycle.public_id},
        attempts=0,
        max_attempts=3,
    )
    db_session.add(job)
    db_session.flush()
    return job


def _create_shortlisted_paper(
    db_session: Session,
    cycle: ResearchCycleModel,
) -> PaperCardModel:
    retrieval = SourceRetrievalSessionModel(
        public_id=generate_public_id("retsess"),
        cycle_id=cycle.id,
        source_type="arxiv_metadata",
        query_params={},
        status="completed",
    )
    db_session.add(retrieval)
    db_session.flush()
    paper = PaperCardModel(
        public_id=generate_public_id("paper"),
        cycle_id=cycle.id,
        retrieval_session_id=retrieval.id,
        source_type="arxiv",
        external_id="2401.00001",
        title="Candidate paper",
        abstract="Paper abstract",
        lifecycle_status="shortlisted",
        triage_score=0.9,
        shortlist_rank=1,
        content_hash="paper-hash",
    )
    db_session.add(paper)
    db_session.flush()
    return paper


def test_evidence_extraction_operator_without_papers_stops(db_session, config, cycle):
    services.sync_skill_catalog(db_session, config)
    job = _create_job(db_session, cycle, "evidence_extraction")

    result = evidence_extraction_operator(db_session, config, SYSTEM_ACTOR, cycle, job)

    assert result.next_actions == []
    assert result.state_patch.context["total_evidence"] == 0
    assert "No shortlisted papers" in result.operator_report.body_markdown
    assert any(
        item.operator_name == "evidence_extraction"
        for item in result.skill_execution_records
    )


def test_hypothesis_generation_operator_without_evidence_stops(db_session, config, cycle):
    services.sync_skill_catalog(db_session, config)
    job = _create_job(db_session, cycle, "hypothesis_generation")

    result = hypothesis_generation_operator(db_session, config, SYSTEM_ACTOR, cycle, job)

    assert result.next_actions == []
    assert result.state_patch.context["hypothesis_count"] == 0
    assert "hypothesis generation was skipped" in result.operator_report.body_markdown.lower()
    assert any(
        item.operator_name == "hypothesis_generation"
        for item in result.skill_execution_records
    )


def test_hypothesis_critique_operator_without_generated_hypotheses_stops(db_session, config, cycle):
    services.sync_skill_catalog(db_session, config)
    job = _create_job(db_session, cycle, "hypothesis_critique")

    result = hypothesis_critique_operator(db_session, config, SYSTEM_ACTOR, cycle, job)

    assert result.next_actions == []
    assert result.state_patch.context["ranked_count"] == 0
    assert "portfolio ranking were skipped" in result.operator_report.body_markdown.lower()
    assert any(
        item.operator_name == "hypothesis_critique"
        for item in result.skill_execution_records
    )


def test_protocol_compilation_operator_without_approved_hypotheses_stops(db_session, config, cycle):
    services.sync_skill_catalog(db_session, config)
    _create_shortlisted_paper(db_session, cycle)
    job = _create_job(db_session, cycle, "protocol_compilation")

    result = protocol_compilation_operator(db_session, config, SYSTEM_ACTOR, cycle, job)

    assert result.next_actions == []
    assert result.state_patch.context["phase"] == "protocol_compilation"
    assert "No approved hypotheses" in result.operator_report.body_markdown
    assert any(
        item.operator_name == "protocol_compilation"
        for item in result.skill_execution_records
    )
