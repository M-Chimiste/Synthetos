"""Unit tests for same-charter historical comparison helpers."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from libs.storage.base import Base
from libs.storage.models import (
    ExperimentSpecModel,
    FailurePostmortemModel,
    HypothesisCardModel,
    ResearchCharterModel,
    ResearchCycleModel,
    RunRecordModel,
    VerificationReportModel,
)
from libs.verification.historical import collect_historical_memory_refs, find_comparable_runs


def _make_run(
    session,
    *,
    cycle_id: int,
    spec_id: int,
    public_id: str,
    accuracy: float,
) -> RunRecordModel:
    run = RunRecordModel(
        public_id=public_id,
        cycle_id=cycle_id,
        experiment_spec_id=spec_id,
        status="succeeded",
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
        metrics_summary={"accuracy": accuracy},
        artifact_manifest={},
        attempt_count=1,
    )
    session.add(run)
    session.flush()
    return run


def test_find_comparable_runs_uses_same_charter_history_only():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    charter = ResearchCharterModel(
        public_id="charter-shared",
        title="Shared charter",
        problem_statement="Problem",
        success_criteria={},
        budget_envelope={},
        source_scope={},
        stop_conditions={},
        constraints={},
    )
    other_charter = ResearchCharterModel(
        public_id="charter-other",
        title="Other charter",
        problem_statement="Other",
        success_criteria={},
        budget_envelope={},
        source_scope={},
        stop_conditions={},
        constraints={},
    )
    session.add_all([charter, other_charter])
    session.flush()

    cycle_one = ResearchCycleModel(
        public_id="cycle-1",
        charter_id=charter.id,
        current_status="ready",
    )
    cycle_two = ResearchCycleModel(
        public_id="cycle-2",
        charter_id=charter.id,
        current_status="ready",
    )
    other_cycle = ResearchCycleModel(
        public_id="cycle-3",
        charter_id=other_charter.id,
        current_status="ready",
    )
    session.add_all([cycle_one, cycle_two, other_cycle])
    session.flush()

    hyp_one = HypothesisCardModel(
        public_id="hyp-1",
        cycle_id=cycle_one.id,
        title="Hypothesis",
        statement="Statement",
        rationale="R",
        approach_summary="A",
        status="approved",
        model_route_id="route",
        prompt_id="prompt",
    )
    hyp_two = HypothesisCardModel(
        public_id="hyp-2",
        cycle_id=cycle_two.id,
        title="Hypothesis",
        statement="Statement",
        rationale="R",
        approach_summary="A",
        status="approved",
        model_route_id="route",
        prompt_id="prompt",
    )
    hyp_other = HypothesisCardModel(
        public_id="hyp-3",
        cycle_id=other_cycle.id,
        title="Hypothesis",
        statement="Statement",
        rationale="R",
        approach_summary="A",
        status="approved",
        model_route_id="route",
        prompt_id="prompt",
    )
    session.add_all([hyp_one, hyp_two, hyp_other])
    session.flush()

    spec_one = ExperimentSpecModel(
        public_id="spec-1",
        cycle_id=cycle_one.id,
        hypothesis_card_id=hyp_one.id,
        title="Same Spec",
        objective="Obj",
        baseline_description="Baseline",
        method_description="Method",
        status="valid",
        model_route_id="route",
        prompt_id="prompt",
    )
    spec_two = ExperimentSpecModel(
        public_id="spec-2",
        cycle_id=cycle_two.id,
        hypothesis_card_id=hyp_two.id,
        title="Same Spec",
        objective="Obj",
        baseline_description="Baseline",
        method_description="Method",
        status="valid",
        model_route_id="route",
        prompt_id="prompt",
    )
    spec_other = ExperimentSpecModel(
        public_id="spec-3",
        cycle_id=other_cycle.id,
        hypothesis_card_id=hyp_other.id,
        title="Same Spec",
        objective="Obj",
        baseline_description="Baseline",
        method_description="Method",
        status="valid",
        model_route_id="route",
        prompt_id="prompt",
    )
    session.add_all([spec_one, spec_two, spec_other])
    session.flush()

    prior_run = _make_run(
        session,
        cycle_id=cycle_one.id,
        spec_id=spec_one.id,
        public_id="run-prior",
        accuracy=0.81,
    )
    current_run = _make_run(
        session,
        cycle_id=cycle_two.id,
        spec_id=spec_two.id,
        public_id="run-current",
        accuracy=0.9,
    )
    _make_run(
        session,
        cycle_id=other_cycle.id,
        spec_id=spec_other.id,
        public_id="run-other",
        accuracy=0.95,
    )

    comparable = find_comparable_runs(
        session,
        current_run,
        spec_two,
        charter_id=charter.id,
    )

    assert [run.public_id for run in comparable] == [prior_run.public_id]

    session.close()
    engine.dispose()


def test_collect_historical_memory_refs_includes_verification_and_postmortem():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    charter = ResearchCharterModel(
        public_id="charter-memory",
        title="Shared charter",
        problem_statement="Problem",
        success_criteria={},
        budget_envelope={},
        source_scope={},
        stop_conditions={},
        constraints={},
    )
    session.add(charter)
    session.flush()
    cycle = ResearchCycleModel(
        public_id="cycle-memory",
        charter_id=charter.id,
        current_status="ready",
    )
    session.add(cycle)
    session.flush()
    hyp = HypothesisCardModel(
        public_id="hyp-memory",
        cycle_id=cycle.id,
        title="Hypothesis",
        statement="Statement",
        rationale="R",
        approach_summary="A",
        status="approved",
        model_route_id="route",
        prompt_id="prompt",
    )
    session.add(hyp)
    session.flush()
    spec = ExperimentSpecModel(
        public_id="spec-memory",
        cycle_id=cycle.id,
        hypothesis_card_id=hyp.id,
        title="Spec",
        objective="Obj",
        baseline_description="Baseline",
        method_description="Method",
        status="valid",
        model_route_id="route",
        prompt_id="prompt",
    )
    session.add(spec)
    session.flush()
    run = _make_run(
        session,
        cycle_id=cycle.id,
        spec_id=spec.id,
        public_id="run-memory",
        accuracy=0.82,
    )
    vr = VerificationReportModel(
        public_id="vr-memory",
        cycle_id=cycle.id,
        run_record_id=run.id,
        experiment_spec_id=spec.id,
        hypothesis_card_id=hyp.id,
        outcome="tentative",
        outcome_rationale="Rationale",
        baseline_comparison={},
        historical_comparisons=[],
        metric_sanity_checks=[],
        artifact_checks=[],
        output_contract_checks=[],
        leakage_signals=[],
        split_validation={},
        rerun_note="Retry",
        reviewer_summary="Needs more evidence",
        model_route_id="route",
        prompt_id="prompt",
    )
    pm = FailurePostmortemModel(
        public_id="pm-memory",
        cycle_id=cycle.id,
        run_record_id=run.id,
        verification_report_id=None,
        failure_class="resource_limit",
        failure_stage="verification",
        root_cause_summary="GPU ran out of memory.",
        contributing_factors=[],
        remediation_suggestions=[],
        retrieval_hints=[],
        protocol_update_hints=[],
        similar_prior_failures=[],
        model_route_id="route",
        prompt_id="prompt",
    )
    session.add_all([vr, pm])
    session.flush()

    refs = collect_historical_memory_refs(session, [run])
    assert refs[0]["verification_report_public_id"] == "vr-memory"
    assert refs[0]["postmortem_public_id"] == "pm-memory"
    assert refs[0]["root_cause_summary"] == "GPU ran out of memory."

    session.close()
    engine.dispose()
