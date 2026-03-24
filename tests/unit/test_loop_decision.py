"""Tests for autonomous loop decision engine."""

from __future__ import annotations

from libs.core.budget import BudgetStatus
from libs.core.policy import AutonomyPolicyConfig
from libs.orchestration.loop_decision import LoopDecision, decide_next_step
from libs.orchestration.repetition import RepetitionCheck


def _default_policy(**overrides: object) -> AutonomyPolicyConfig:
    kwargs = {
        "mode": "autonomous",
        "auto_pivot_on_stall": True,
        "auto_pivot_on_regression": True,
        "auto_continue_on_advancing": True,
        "auto_regenerate_hypotheses": True,
        "escalate_on_portfolio_exhausted": True,
    }
    kwargs.update(overrides)
    return AutonomyPolicyConfig(**kwargs)


def _within_budget() -> BudgetStatus:
    return BudgetStatus(within_budget=True, remaining_runs=10)


def _exceeded_budget() -> BudgetStatus:
    return BudgetStatus(within_budget=False, reason="Total run budget exhausted")


def _no_repetition() -> RepetitionCheck:
    return RepetitionCheck(is_repetition=False)


class TestDecideNextStep:
    def test_budget_exhausted_stops(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_exceeded_budget(),
            directional_signal="advancing",
            verification_outcome="robust",
            repetition_check=_no_repetition(),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.BUDGET_EXHAUSTED

    def test_success_criteria_met_stops(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="advancing",
            verification_outcome="robust",
            repetition_check=_no_repetition(),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=True,
        )
        assert result.decision == LoopDecision.SUCCESS_CRITERIA_MET

    def test_advancing_continues(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="advancing",
            verification_outcome="robust",
            repetition_check=_no_repetition(),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.CONTINUE_SAME_HYPOTHESIS

    def test_stalled_under_max_varies(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="stalled",
            verification_outcome="tentative",
            repetition_check=_no_repetition(),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.VARY_PARAMETERS

    def test_stalled_over_max_pivots(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="stalled",
            verification_outcome="tentative",
            repetition_check=_no_repetition(),
            hypothesis_run_count=5,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.PIVOT_HYPOTHESIS

    def test_regressing_pivots(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="regressing",
            verification_outcome="rejected",
            repetition_check=_no_repetition(),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.PIVOT_HYPOTHESIS

    def test_noisy_continues(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="noisy",
            verification_outcome="tentative",
            repetition_check=_no_repetition(),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.CONTINUE_SAME_HYPOTHESIS

    def test_breakthrough_continues(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="breakthrough",
            verification_outcome="robust",
            repetition_check=_no_repetition(),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.CONTINUE_SAME_HYPOTHESIS

    def test_repetition_forces_variation(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="stalled",
            verification_outcome="tentative",
            repetition_check=RepetitionCheck(
                is_repetition=True,
                repetition_type="trace_level",
                detail="Same spec hash",
            ),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.VARY_PARAMETERS

    def test_no_alternatives_regenerates(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="stalled",
            verification_outcome="tentative",
            repetition_check=_no_repetition(),
            hypothesis_run_count=5,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=False,
            regeneration_attempted=False,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.REGENERATE_PORTFOLIO

    def test_regeneration_attempted_escalates(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="stalled",
            verification_outcome="tentative",
            repetition_check=_no_repetition(),
            hypothesis_run_count=5,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=False,
            regeneration_attempted=True,
            success_criteria_met=False,
        )
        assert result.decision == LoopDecision.ESCALATE

    def test_first_iteration_continues(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal=None,
            verification_outcome=None,
            repetition_check=_no_repetition(),
            hypothesis_run_count=0,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
            has_last_run=False,
        )
        assert result.decision == LoopDecision.CONTINUE_SAME_HYPOTHESIS

    def test_invalid_without_positive_signal_pivots(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal=None,
            verification_outcome="invalid",
            repetition_check=_no_repetition(),
            hypothesis_run_count=1,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
            has_last_run=True,
        )
        assert result.decision == LoopDecision.PIVOT_HYPOTHESIS

    def test_rejected_tradeoff_pivots(self) -> None:
        result = decide_next_step(
            autonomy_policy=_default_policy(),
            budget_status=_within_budget(),
            directional_signal="advancing",
            verification_outcome="rejected",
            repetition_check=_no_repetition(),
            hypothesis_run_count=2,
            max_runs_per_hypothesis=5,
            portfolio_has_alternatives=True,
            regeneration_attempted=False,
            success_criteria_met=False,
            tradeoff_resolution={"resolution": "reject_tradeoff"},
        )
        assert result.decision == LoopDecision.PIVOT_HYPOTHESIS
