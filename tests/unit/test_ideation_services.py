"""Unit tests for libs.ideation.services."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.core.ids import generate_public_id
from libs.ideation.services import (
    build_evidence_summary,
    compute_portfolio_ranking,
    create_evidence_card,
    create_experiment_spec,
    create_hypothesis_card,
    detect_conflicts_and_redundancy,
    get_approved_hypotheses,
    get_papers_for_evidence_extraction,
    list_evidence_for_cycle,
    record_hypothesis_critique,
    reject_experiment_spec,
    validate_experiment_spec,
)
from libs.storage.base import Base
from libs.storage.models import (
    ExperimentSpecModel,
    FailurePostmortemModel,
    PaperCardModel,
    ResearchCharterModel,
    ResearchCycleModel,
    RunRecordModel,
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
def shortlisted_paper(db_session: Session, cycle: ResearchCycleModel):
    ret_session = SourceRetrievalSessionModel(
        public_id=generate_public_id("retsess"),
        cycle_id=cycle.id,
        source_type="arxiv_metadata",
        query_params={},
        status="completed",
    )
    db_session.add(ret_session)
    db_session.flush()
    paper = PaperCardModel(
        public_id=generate_public_id("paper"),
        cycle_id=cycle.id,
        retrieval_session_id=ret_session.id,
        source_type="arxiv",
        external_id="2401.00001",
        title="Test Paper",
        abstract="A test abstract",
        lifecycle_status="shortlisted",
        triage_score=0.9,
        shortlist_rank=1,
        content_hash="test_hash_1",
    )
    db_session.add(paper)
    db_session.flush()
    return paper


# ---------------------------------------------------------------------------
# Evidence tests
# ---------------------------------------------------------------------------


def test_create_evidence_card(db_session, cycle, shortlisted_paper):
    card = create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="NAS reduces search cost by 1000x",
        evidence_type="finding",
        strength="strong",
        relevance_score=0.92,
        relevance_rationale="Directly relevant",
        source_section="results",
        source_quote="Our approach reduces GPU hours by 1000x",
        read_depth="abstract",
        model_route_id="evidence_extractor",
        prompt_id="test_prompt",
    )
    assert card.public_id.startswith("evidence_")
    assert card.claim == "NAS reduces search cost by 1000x"
    assert card.evidence_type == "finding"
    assert card.relevance_score == 0.92


def test_create_multiple_evidence_from_one_paper(db_session, cycle, shortlisted_paper):
    for i in range(3):
        create_evidence_card(
            db_session, cycle.id, shortlisted_paper.id,
            claim=f"Claim {i}",
            evidence_type="finding",
            strength="moderate",
            relevance_score=0.7,
            relevance_rationale="Relevant",
            source_section=None,
            source_quote=None,
            read_depth="abstract",
            model_route_id="ev",
            prompt_id="p",
        )
    cards = list_evidence_for_cycle(db_session, cycle.id)
    assert len(cards) == 3


def test_detect_conflicts_and_redundancy(db_session, cycle, shortlisted_paper):
    create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="NAS reduces search cost significantly",
        evidence_type="finding",
        strength="strong",
        relevance_score=0.9,
        relevance_rationale="Key finding",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )
    # Same claim embedded in a longer string
    create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="The paper shows NAS reduces search cost significantly through weight sharing",
        evidence_type="finding",
        strength="moderate",
        relevance_score=0.85,
        relevance_rationale="Related finding",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )
    conflict_count, redundancy_count = detect_conflicts_and_redundancy(db_session, cycle.id)
    assert redundancy_count == 1


def test_detect_conflicts_and_redundancy_opposing_claims(db_session, cycle, shortlisted_paper):
    first = create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="The method improves validation accuracy on CIFAR benchmark",
        evidence_type="finding",
        strength="strong",
        relevance_score=0.91,
        relevance_rationale="Direct experimental result",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )
    second = create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="The method worsens validation accuracy on CIFAR benchmark",
        evidence_type="finding",
        strength="moderate",
        relevance_score=0.82,
        relevance_rationale="Countervailing result",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )

    conflict_count, redundancy_count = detect_conflicts_and_redundancy(db_session, cycle.id)

    assert conflict_count == 1
    assert redundancy_count == 0
    assert second.public_id in (first.conflict_with or [])
    assert first.public_id in (second.conflict_with or [])
    assert "opposing polarity cues" in (first.conflict_notes or "")


def test_detect_conflicts_and_redundancy_unrelated_claims(db_session, cycle, shortlisted_paper):
    create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="The method improves validation accuracy on CIFAR benchmark",
        evidence_type="finding",
        strength="strong",
        relevance_score=0.91,
        relevance_rationale="Direct experimental result",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )
    create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="The dataset uses synthetic labels for pretraining",
        evidence_type="dataset",
        strength="moderate",
        relevance_score=0.6,
        relevance_rationale="Dataset detail",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )

    conflict_count, redundancy_count = detect_conflicts_and_redundancy(db_session, cycle.id)

    assert conflict_count == 0
    assert redundancy_count == 0


def test_get_papers_for_evidence_extraction(db_session, cycle, shortlisted_paper):
    papers = get_papers_for_evidence_extraction(db_session, cycle.id)
    assert len(papers) == 1
    assert papers[0].public_id == shortlisted_paper.public_id

    # After creating evidence, paper should no longer appear
    create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="Test",
        evidence_type="finding",
        strength="moderate",
        relevance_score=0.5,
        relevance_rationale="Test",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )
    papers = get_papers_for_evidence_extraction(db_session, cycle.id)
    assert len(papers) == 0


def test_build_evidence_summary(db_session, cycle, shortlisted_paper):
    create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="Finding A",
        evidence_type="finding",
        strength="strong",
        relevance_score=0.9,
        relevance_rationale="Good",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )
    create_evidence_card(
        db_session, cycle.id, shortlisted_paper.id,
        claim="Method B",
        evidence_type="method",
        strength="moderate",
        relevance_score=0.7,
        relevance_rationale="OK",
        source_section=None,
        source_quote=None,
        read_depth="abstract",
        model_route_id="ev",
        prompt_id="p",
    )
    summary = build_evidence_summary(db_session, cycle.id)
    assert summary["total_evidence"] == 2
    assert summary["by_type"]["finding"] == 1
    assert summary["by_type"]["method"] == 1
    assert summary["by_strength"]["strong"] == 1
    assert summary["by_strength"]["moderate"] == 1


# ---------------------------------------------------------------------------
# Hypothesis tests
# ---------------------------------------------------------------------------


def test_create_hypothesis_card(db_session, cycle):
    card = create_hypothesis_card(
        db_session, cycle.id,
        title="Test Hypothesis",
        statement="We hypothesize that...",
        rationale="Because evidence shows...",
        approach_summary="Train a model and compare",
        supporting_evidence=["evidence_001"],
        counter_evidence=[],
        model_route_id="ideation",
        prompt_id="test_prompt",
    )
    assert card.public_id.startswith("hyp_")
    assert card.status == "generated"
    assert card.title == "Test Hypothesis"


def test_compute_portfolio_ranking(db_session, cycle):
    for i, (n, f, im) in enumerate([(0.8, 0.9, 0.7), (0.5, 0.5, 0.5), (0.9, 0.8, 0.9)]):
        h = create_hypothesis_card(
            db_session, cycle.id,
            title=f"Hyp {i}",
            statement=f"Statement {i}",
            rationale="R",
            approach_summary="A",
            supporting_evidence=[],
            counter_evidence=[],
            model_route_id="ideation",
            prompt_id="p",
        )
        record_hypothesis_critique(db_session, h, {
            "novelty_score": n,
            "feasibility_score": f,
            "impact_score": im,
            "critique_summary": "OK",
            "issues": [],
        })

    ranked = compute_portfolio_ranking(db_session, cycle.id, auto_approve_top_n=2)
    assert len(ranked) == 3
    assert ranked[0].portfolio_rank == 1
    # Highest composite score: 0.9 * 0.8 * 0.9 = 0.648
    assert ranked[0].portfolio_score == pytest.approx(0.648, abs=0.01)
    assert ranked[1].portfolio_rank == 2
    assert ranked[2].portfolio_rank == 3


def test_auto_approve_top_n(db_session, cycle):
    for i in range(5):
        h = create_hypothesis_card(
            db_session, cycle.id,
            title=f"Hyp {i}",
            statement="S",
            rationale="R",
            approach_summary="A",
            supporting_evidence=[],
            counter_evidence=[],
            model_route_id="ideation",
            prompt_id="p",
        )
        record_hypothesis_critique(db_session, h, {
            "novelty_score": 0.5 + i * 0.1,
            "feasibility_score": 0.5 + i * 0.1,
            "impact_score": 0.5 + i * 0.1,
            "critique_summary": "OK",
            "issues": [],
        })

    compute_portfolio_ranking(db_session, cycle.id, auto_approve_top_n=3)
    approved = get_approved_hypotheses(db_session, cycle.id)
    assert len(approved) == 3
    assert all(h.status == "approved" for h in approved)


def test_compute_portfolio_ranking_applies_failure_memory_penalty(db_session, cycle):
    low_risk = create_hypothesis_card(
        db_session, cycle.id,
        title="Stable idea",
        statement="S1",
        rationale="R1",
        approach_summary="A1",
        supporting_evidence=[],
        counter_evidence=[],
        model_route_id="ideation",
        prompt_id="p",
    )
    penalized = create_hypothesis_card(
        db_session, cycle.id,
        title="Penalty target",
        statement="S2",
        rationale="R2",
        approach_summary="A2",
        supporting_evidence=[],
        counter_evidence=[],
        model_route_id="ideation",
        prompt_id="p",
    )
    record_hypothesis_critique(db_session, low_risk, {
        "novelty_score": 0.7,
        "feasibility_score": 0.7,
        "impact_score": 0.7,
        "critique_summary": "OK",
        "issues": [],
    })
    record_hypothesis_critique(db_session, penalized, {
        "novelty_score": 0.9,
        "feasibility_score": 0.9,
        "impact_score": 0.9,
        "critique_summary": "OK",
        "issues": [],
    })

    charter_id = cycle.charter_id
    prior_cycle = ResearchCycleModel(
        public_id=generate_public_id("cycle"),
        charter_id=charter_id,
        current_status="ready",
    )
    db_session.add(prior_cycle)
    db_session.flush()
    prior_hyp = create_hypothesis_card(
        db_session, prior_cycle.id,
        title="Penalty target",
        statement="Prior",
        rationale="Prior",
        approach_summary="Prior",
        supporting_evidence=[],
        counter_evidence=[],
        model_route_id="ideation",
        prompt_id="p",
    )
    spec = ExperimentSpecModel(
        public_id=generate_public_id("expspec"),
        cycle_id=prior_cycle.id,
        hypothesis_card_id=prior_hyp.id,
        title="Penalty target",
        objective="Obj",
        baseline_description="Baseline",
        method_description="Method",
        status="valid",
        model_route_id="route",
        prompt_id="prompt",
    )
    db_session.add(spec)
    db_session.flush()
    for index in range(2):
        run = RunRecordModel(
            public_id=generate_public_id("run"),
            cycle_id=prior_cycle.id,
            experiment_spec_id=spec.id,
            status="failed",
            execution_profile="cpu-small",
            workspace_path="/tmp/workspace",
            artifact_root="/tmp/artifacts",
            image="python:3.12",
            build_recipe={},
            command=["python", "train.py"],
            env_vars={},
            mounts=[],
            hardware_profile="cpu-small",
            timeout_seconds=60,
            memory_limit_mb=1024,
            cpu_limit="2",
            gpu_enabled=False,
            network_mode="disabled",
            bound_skill_keys=[],
            prompt_lineage=[],
            model_lineage=[],
            latest_resource_snapshot={},
            metrics_summary={},
            artifact_manifest={},
            failure_classification="resource_limit",
            verification_outcome="invalid",
            attempt_count=1,
        )
        db_session.add(run)
        db_session.flush()
        db_session.add(
            FailurePostmortemModel(
                public_id=generate_public_id("pm"),
                cycle_id=prior_cycle.id,
                run_record_id=run.id,
                verification_report_id=None,
                failure_class="resource_limit",
                failure_stage="execution",
                root_cause_summary=f"Run {index} exhausted memory.",
                contributing_factors=[],
                remediation_suggestions=[],
                retrieval_hints=[],
                protocol_update_hints=[],
                similar_prior_failures=[],
                model_route_id="route",
                prompt_id="prompt",
            )
        )
    db_session.flush()

    ranked = compute_portfolio_ranking(
        db_session,
        cycle.id,
        auto_approve_top_n=2,
        charter_id=charter_id,
    )
    ranked_by_title = {item.title: item for item in ranked}
    assert (ranked_by_title["Penalty target"].portfolio_score or 0.0) < 0.729
    assert "portfolio penalty" in (
        ranked_by_title["Penalty target"].ranking_rationale or ""
    ).lower()


# ---------------------------------------------------------------------------
# ExperimentSpec tests
# ---------------------------------------------------------------------------


def test_create_experiment_spec(db_session, cycle):
    hyp = create_hypothesis_card(
        db_session, cycle.id,
        title="H",
        statement="S",
        rationale="R",
        approach_summary="A",
        supporting_evidence=[],
        counter_evidence=[],
        model_route_id="ideation",
        prompt_id="p",
    )
    spec = create_experiment_spec(
        db_session, cycle.id, hyp.id,
        spec_data={
            "title": "Test Experiment",
            "objective": "Test objective",
            "baseline_description": "Baseline",
            "method_description": "Method",
            "metrics": [{"name": "accuracy", "direction": "higher_is_better"}],
            "datasets": [{"name": "CIFAR-10", "source": "torchvision"}],
            "expected_outputs": [{"description": "Table", "format": "csv"}],
        },
        model_route_id="protocol_drafter",
        prompt_id="p",
    )
    assert spec.public_id.startswith("expspec_")
    assert spec.status == "draft"
    assert spec.title == "Test Experiment"


def test_validate_experiment_spec_valid(db_session, cycle):
    hyp = create_hypothesis_card(
        db_session, cycle.id,
        title="H", statement="S", rationale="R", approach_summary="A",
        supporting_evidence=[], counter_evidence=[],
        model_route_id="ideation", prompt_id="p",
    )
    spec = create_experiment_spec(
        db_session, cycle.id, hyp.id,
        spec_data={
            "title": "Exp",
            "objective": "Obj",
            "baseline_description": "Baseline desc",
            "method_description": "Method",
            "metrics": [{"name": "acc"}],
            "datasets": [{"name": "D"}],
            "expected_outputs": [{"description": "O", "format": "csv"}],
            "stop_conditions": [{"condition": "diverge", "action": "stop"}],
        },
        model_route_id="protocol_drafter",
        prompt_id="p",
    )
    issues = validate_experiment_spec(spec)
    blocking = [i for i in issues if i["severity"] == "blocking"]
    assert len(blocking) == 0


def test_validate_experiment_spec_missing_metrics(db_session, cycle):
    hyp = create_hypothesis_card(
        db_session, cycle.id,
        title="H", statement="S", rationale="R", approach_summary="A",
        supporting_evidence=[], counter_evidence=[],
        model_route_id="ideation", prompt_id="p",
    )
    spec = create_experiment_spec(
        db_session, cycle.id, hyp.id,
        spec_data={
            "title": "Exp",
            "objective": "Obj",
            "baseline_description": "Baseline",
            "method_description": "Method",
            "metrics": [],
            "datasets": [{"name": "D"}],
            "expected_outputs": [{"description": "O", "format": "csv"}],
        },
        model_route_id="protocol_drafter",
        prompt_id="p",
    )
    issues = validate_experiment_spec(spec)
    blocking = [i for i in issues if i["severity"] == "blocking"]
    assert any(i["field"] == "metrics" for i in blocking)


def test_validate_experiment_spec_missing_datasets(db_session, cycle):
    hyp = create_hypothesis_card(
        db_session, cycle.id,
        title="H", statement="S", rationale="R", approach_summary="A",
        supporting_evidence=[], counter_evidence=[],
        model_route_id="ideation", prompt_id="p",
    )
    spec = create_experiment_spec(
        db_session, cycle.id, hyp.id,
        spec_data={
            "title": "Exp",
            "objective": "Obj",
            "baseline_description": "Baseline",
            "method_description": "Method",
            "metrics": [{"name": "acc"}],
            "datasets": [],
            "expected_outputs": [{"description": "O", "format": "csv"}],
        },
        model_route_id="protocol_drafter",
        prompt_id="p",
    )
    issues = validate_experiment_spec(spec)
    blocking = [i for i in issues if i["severity"] == "blocking"]
    assert any(i["field"] == "datasets" for i in blocking)


def test_validate_experiment_spec_empty_baseline(db_session, cycle):
    hyp = create_hypothesis_card(
        db_session, cycle.id,
        title="H", statement="S", rationale="R", approach_summary="A",
        supporting_evidence=[], counter_evidence=[],
        model_route_id="ideation", prompt_id="p",
    )
    spec = create_experiment_spec(
        db_session, cycle.id, hyp.id,
        spec_data={
            "title": "Exp",
            "objective": "Obj",
            "baseline_description": "",
            "method_description": "Method",
            "metrics": [{"name": "acc"}],
            "datasets": [{"name": "D"}],
            "expected_outputs": [{"description": "O", "format": "csv"}],
        },
        model_route_id="protocol_drafter",
        prompt_id="p",
    )
    issues = validate_experiment_spec(spec)
    blocking = [i for i in issues if i["severity"] == "blocking"]
    assert any(i["field"] == "baseline_description" for i in blocking)


def test_reject_experiment_spec(db_session, cycle):
    hyp = create_hypothesis_card(
        db_session, cycle.id,
        title="H", statement="S", rationale="R", approach_summary="A",
        supporting_evidence=[], counter_evidence=[],
        model_route_id="ideation", prompt_id="p",
    )
    spec = create_experiment_spec(
        db_session, cycle.id, hyp.id,
        spec_data={
            "title": "Exp",
            "objective": "Obj",
            "baseline_description": "B",
            "method_description": "M",
        },
        model_route_id="protocol_drafter",
        prompt_id="p",
    )
    reject_experiment_spec(db_session, spec, "Missing critical fields")
    assert spec.status == "rejected"
    assert spec.rejection_reason == "Missing critical fields"
