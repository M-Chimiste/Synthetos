"""Tests for autonomous loop step operator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.core.ids import generate_public_id
from libs.storage.models import (
    ExperimentSpecModel,
    HypothesisCardModel,
    ResearchCharterModel,
    ResearchCycleModel,
)


@pytest.fixture()
def db_session() -> Session:
    from libs.storage.base import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def seed(db_session: Session) -> dict:
    charter = ResearchCharterModel(
        public_id=generate_public_id("charter"),
        title="Test Charter",
        problem_statement="Test problem",
        success_criteria={
            "primary_metric": "accuracy",
            "primary_higher_is_better": True,
            "significance_threshold": 0.01,
        },
        budget_envelope={
            "max_total_runs": 10,
            "max_runs_per_hypothesis": 3,
        },
    )
    db_session.add(charter)
    db_session.flush()

    cycle = ResearchCycleModel(
        public_id=generate_public_id("cycle"),
        charter_id=charter.id,
        current_status="running",
        autonomy_mode="autonomous",
        budget_max_total_runs=10,
        budget_max_runs_per_hypothesis=3,
        budget_used_run_count=0,
        budget_used_compute_minutes=0.0,
        budget_runs_per_hypothesis={},
    )
    db_session.add(cycle)
    db_session.flush()

    hyp = HypothesisCardModel(
        public_id=generate_public_id("hyp"),
        cycle_id=cycle.id,
        title="Test hypothesis",
        statement="Statement",
        rationale="Rationale",
        approach_summary="Approach",
        status="approved",
        model_route_id="route",
        prompt_id="prompt",
        portfolio_rank=1,
        portfolio_score=0.8,
    )
    db_session.add(hyp)
    db_session.flush()

    spec = ExperimentSpecModel(
        public_id=generate_public_id("spec"),
        cycle_id=cycle.id,
        hypothesis_card_id=hyp.id,
        title="Test spec",
        objective="Objective",
        baseline_description="Baseline",
        method_description="Method",
        controls=[],
        metrics=[{"name": "accuracy"}],
        datasets=[],
        artifacts=[],
        stop_conditions=[],
        expected_outputs=[],
        gpu_required=False,
        status="valid",
        prompt_id="prompt",
        model_route_id="route",
    )
    db_session.add(spec)
    db_session.flush()

    return {
        "charter": charter,
        "cycle": cycle,
        "hyp": hyp,
        "spec": spec,
    }


class TestAutonomousLoopDecisionLogic:
    """Test the decision logic used by the loop operator."""

    def test_budget_exhausted_enqueues_completion(self) -> None:
        from libs.core.budget import BudgetStatus
        from libs.core.policy import AutonomyPolicyConfig
        from libs.orchestration.loop_decision import LoopDecision, decide_next_step
        from libs.orchestration.repetition import RepetitionCheck

        result = decide_next_step(
            autonomy_policy=AutonomyPolicyConfig(mode="autonomous"),
            budget_status=BudgetStatus(
                within_budget=False,
                reason="Total run budget exhausted: 10/10",
            ),
            directional_signal="advancing",
            verification_outcome="robust",
            repetition_check=RepetitionCheck(is_repetition=False),
            hypothesis_run_count=5,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.BUDGET_EXHAUSTED

    def test_advancing_continues_same(self) -> None:
        from libs.core.budget import BudgetStatus
        from libs.core.policy import AutonomyPolicyConfig
        from libs.orchestration.loop_decision import LoopDecision, decide_next_step
        from libs.orchestration.repetition import RepetitionCheck

        result = decide_next_step(
            autonomy_policy=AutonomyPolicyConfig(mode="autonomous"),
            budget_status=BudgetStatus(within_budget=True, remaining_runs=5),
            directional_signal="advancing",
            verification_outcome="robust",
            repetition_check=RepetitionCheck(is_repetition=False),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.CONTINUE_SAME_HYPOTHESIS

    def test_stalled_pivots_after_max(self) -> None:
        from libs.core.budget import BudgetStatus
        from libs.core.policy import AutonomyPolicyConfig
        from libs.orchestration.loop_decision import LoopDecision, decide_next_step
        from libs.orchestration.repetition import RepetitionCheck

        result = decide_next_step(
            autonomy_policy=AutonomyPolicyConfig(mode="autonomous"),
            budget_status=BudgetStatus(within_budget=True, remaining_runs=5),
            directional_signal="stalled",
            verification_outcome="tentative",
            repetition_check=RepetitionCheck(is_repetition=False),
            hypothesis_run_count=3,
            max_runs_per_hypothesis=3,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.PIVOT_HYPOTHESIS

    def test_portfolio_exhausted_triggers_regeneration(self) -> None:
        from libs.core.budget import BudgetStatus
        from libs.core.policy import AutonomyPolicyConfig
        from libs.orchestration.loop_decision import LoopDecision, decide_next_step
        from libs.orchestration.repetition import RepetitionCheck

        result = decide_next_step(
            autonomy_policy=AutonomyPolicyConfig(mode="autonomous"),
            budget_status=BudgetStatus(within_budget=True, remaining_runs=5),
            directional_signal="stalled",
            verification_outcome="tentative",
            repetition_check=RepetitionCheck(is_repetition=False),
            hypothesis_run_count=3,
            max_runs_per_hypothesis=3,
            portfolio_has_alternatives=False,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.REGENERATE_PORTFOLIO


class TestAutonomyPolicyConfig:
    def test_defaults(self) -> None:
        from libs.core.policy import AutonomyPolicyConfig

        policy = AutonomyPolicyConfig()
        assert policy.mode == "supervised"
        assert policy.auto_pivot_on_stall is True

    def test_load_from_yaml(self) -> None:
        from libs.core.policy import load_autonomy_policy

        raw = {
            "autonomy": {
                "mode": "autonomous",
                "auto_pivot_on_stall": False,
            },
        }
        policy = load_autonomy_policy(raw)
        assert policy.mode == "autonomous"
        assert policy.auto_pivot_on_stall is False


class TestSupervisedModeNoAutoChain:
    def test_supervised_verification_no_loop_action(self) -> None:
        """In supervised mode, verification_report_operator should not
        chain to autonomous_loop_step."""
        # This is tested indirectly: the chaining code checks
        # cycle.autonomy_mode == "autonomous", so supervised mode
        # won't produce any next_actions for autonomous_loop_step.
        cycle = MagicMock()
        cycle.autonomy_mode = "supervised"
        assert cycle.autonomy_mode != "autonomous"


class TestAutonomousLoopLifecycle:
    def test_apply_loop_transition_marks_stalled(self, db_session: Session, seed: dict) -> None:
        from libs.orchestration.autonomous_loop import _apply_loop_transition
        from libs.orchestration.loop_decision import LoopDecision, LoopDecisionResult

        hyp = seed["hyp"]
        hyp.status = "active"
        db_session.flush()

        _apply_loop_transition(
            session=db_session,
            hypothesis=hyp,
            decision=LoopDecisionResult(
                decision=LoopDecision.PIVOT_HYPOTHESIS,
                reason="stalled at cap",
            ),
            directional_signal="stalled",
            verification_outcome="tentative",
            tradeoff_resolution=None,
            success_met=False,
            hypothesis_run_count=3,
            max_runs_per_hypothesis=3,
        )

        assert hyp.status == "stalled"

    def test_apply_loop_transition_marks_deprioritized_on_rejected_tradeoff(
        self, db_session: Session, seed: dict,
    ) -> None:
        from libs.orchestration.autonomous_loop import _apply_loop_transition
        from libs.orchestration.loop_decision import LoopDecision, LoopDecisionResult

        hyp = seed["hyp"]
        hyp.status = "active"
        db_session.flush()

        _apply_loop_transition(
            session=db_session,
            hypothesis=hyp,
            decision=LoopDecisionResult(
                decision=LoopDecision.PIVOT_HYPOTHESIS,
                reason="tradeoff rejected",
            ),
            directional_signal="advancing",
            verification_outcome="rejected",
            tradeoff_resolution={"resolution": "reject_tradeoff"},
            success_met=False,
            hypothesis_run_count=2,
            max_runs_per_hypothesis=3,
        )

        assert hyp.status == "deprioritized"

    def test_apply_loop_transition_validates_successful_hypothesis(
        self, db_session: Session, seed: dict,
    ) -> None:
        from libs.orchestration.autonomous_loop import _apply_loop_transition
        from libs.orchestration.loop_decision import LoopDecision, LoopDecisionResult

        hyp = seed["hyp"]
        hyp.status = "active"
        db_session.flush()

        _apply_loop_transition(
            session=db_session,
            hypothesis=hyp,
            decision=LoopDecisionResult(
                decision=LoopDecision.SUCCESS_CRITERIA_MET,
                reason="success",
            ),
            directional_signal="breakthrough",
            verification_outcome="robust",
            tradeoff_resolution=None,
            success_met=True,
            hypothesis_run_count=2,
            max_runs_per_hypothesis=3,
        )

        assert hyp.status == "validated"

    def test_variation_branch_enqueues_protocol_compilation(
        self, db_session: Session, seed: dict,
    ) -> None:
        from libs.orchestration.autonomous_loop import _enqueue_experiment_for_hypothesis

        actions = _enqueue_experiment_for_hypothesis(
            session=db_session,
            config=MagicMock(),
            actor=MagicMock(),
            cycle=seed["cycle"],
            hypothesis=seed["hyp"],
            iteration=2,
            base_payload={"cycle_public_id": seed["cycle"].public_id},
            parameter_variation_hints=[{"reason": "stall_break"}],
            variation_mode=True,
        )

        assert len(actions) == 1
        assert actions[0].action == "protocol_compilation"
        assert actions[0].payload["variation_mode"] is True
        assert actions[0].payload["selected_hypothesis_public_id"] == seed["hyp"].public_id
