"""Pure decision logic for the autonomous experiment loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from libs.core.budget import BudgetStatus
from libs.core.policy import AutonomyPolicyConfig
from libs.orchestration.repetition import RepetitionCheck


class LoopDecision(StrEnum):
    CONTINUE_SAME_HYPOTHESIS = "continue_same"
    VARY_PARAMETERS = "vary_parameters"
    PIVOT_HYPOTHESIS = "pivot_hypothesis"
    REGENERATE_PORTFOLIO = "regenerate_portfolio"
    ESCALATE = "escalate"
    BUDGET_EXHAUSTED = "budget_exhausted"
    SUCCESS_CRITERIA_MET = "success_criteria_met"


@dataclass
class LoopDecisionResult:
    decision: LoopDecision
    reason: str
    next_hypothesis_id: int | None = None
    parameter_variation_hints: list[dict[str, Any]] | None = None


def decide_next_step(
    *,
    autonomy_policy: AutonomyPolicyConfig,
    budget_status: BudgetStatus,
    directional_signal: str | None,
    verification_outcome: str | None,
    repetition_check: RepetitionCheck,
    hypothesis_run_count: int,
    max_runs_per_hypothesis: int | None,
    portfolio_has_alternatives: bool,
    regeneration_attempted: bool,
    success_criteria_met: bool,
    tradeoff_resolution: dict[str, Any] | None = None,
    has_last_run: bool = True,
) -> LoopDecisionResult:
    """Decide the next action for the autonomous loop.

    Pure function — no DB or LLM calls. All state is passed in.
    """
    tradeoff_resolution = tradeoff_resolution or {}

    # 1. Budget check — hard stop
    if not budget_status.within_budget:
        return LoopDecisionResult(
            decision=LoopDecision.BUDGET_EXHAUSTED,
            reason=budget_status.reason or "Budget exhausted",
        )

    # 2. Success criteria — mission accomplished
    if success_criteria_met:
        return LoopDecisionResult(
            decision=LoopDecision.SUCCESS_CRITERIA_MET,
            reason="Success criteria met",
        )

    resolution = str(tradeoff_resolution.get("resolution", "")).lower()
    if resolution == "reject_tradeoff":
        return _pivot_or_regenerate(
            portfolio_has_alternatives,
            regeneration_attempted,
            autonomy_policy,
            reason="Constraint tradeoff rejected by verifier",
        )

    if verification_outcome in {"invalid", "rejected"} and directional_signal not in {
        "advancing",
        "breakthrough",
    }:
        return _pivot_or_regenerate(
            portfolio_has_alternatives,
            regeneration_attempted,
            autonomy_policy,
            reason=f"Verification outcome {verification_outcome} is not promotable",
        )

    # 3. Repetition detection — force variation or pivot
    if repetition_check.is_repetition:
        if (
            repetition_check.repetition_type == "result_level"
            and max_runs_per_hypothesis is not None
            and hypothesis_run_count >= max_runs_per_hypothesis
        ):
            return _pivot_or_regenerate(
                portfolio_has_alternatives,
                regeneration_attempted,
                autonomy_policy,
                reason=(
                    f"Result-level repetition detected and "
                    f"max runs ({max_runs_per_hypothesis}) reached: "
                    f"{repetition_check.detail}"
                ),
            )
        return LoopDecisionResult(
            decision=LoopDecision.VARY_PARAMETERS,
            reason=f"Repetition detected: {repetition_check.detail}",
            parameter_variation_hints=[
                {"reason": "repetition_break"},
            ],
        )

    # 4. Signal-based decisions
    if directional_signal == "advancing":
        if autonomy_policy.auto_continue_on_advancing and verification_outcome in {
            None,
            "tentative",
            "robust",
        }:
            return LoopDecisionResult(
                decision=LoopDecision.CONTINUE_SAME_HYPOTHESIS,
                reason="Advancing — continue with current hypothesis",
            )

    elif directional_signal == "stalled":
        at_limit = (
            max_runs_per_hypothesis is not None
            and hypothesis_run_count >= max_runs_per_hypothesis
        )
        if at_limit and autonomy_policy.auto_pivot_on_stall:
            return _pivot_or_regenerate(
                portfolio_has_alternatives,
                regeneration_attempted,
                autonomy_policy,
                reason=(
                    f"Stalled after {hypothesis_run_count} runs "
                    f"(max: {max_runs_per_hypothesis})"
                ),
            )
        return LoopDecisionResult(
            decision=LoopDecision.VARY_PARAMETERS,
            reason=(
                f"Stalled — varying parameters "
                f"(run {hypothesis_run_count}"
                f"/{max_runs_per_hypothesis or '∞'})"
            ),
            parameter_variation_hints=[{"reason": "stall_break"}],
        )

    elif directional_signal == "regressing":
        if autonomy_policy.auto_pivot_on_regression:
            return _pivot_or_regenerate(
                portfolio_has_alternatives,
                regeneration_attempted,
                autonomy_policy,
                reason="Regressing — pivoting to next hypothesis",
            )

    elif directional_signal == "noisy":
        at_limit = (
            max_runs_per_hypothesis is not None
            and hypothesis_run_count >= max_runs_per_hypothesis
        )
        if verification_outcome == "tentative" and at_limit:
            return LoopDecisionResult(
                decision=LoopDecision.VARY_PARAMETERS,
                reason="Noisy and tentative at run cap — vary parameters before pivoting",
                parameter_variation_hints=[{"reason": "noise_reduction"}],
            )
        return LoopDecisionResult(
            decision=LoopDecision.CONTINUE_SAME_HYPOTHESIS,
            reason="Noisy — more data needed for statistical power",
        )

    elif directional_signal == "breakthrough":
        return LoopDecisionResult(
            decision=LoopDecision.CONTINUE_SAME_HYPOTHESIS,
            reason="Breakthrough — continuing with current hypothesis",
        )

    # 5. First iteration (no signal yet) or unknown signal
    if directional_signal is None and not has_last_run:
        return LoopDecisionResult(
            decision=LoopDecision.CONTINUE_SAME_HYPOTHESIS,
            reason="First iteration — running initial experiment",
        )

    # 6. Fallback: continue
    return LoopDecisionResult(
        decision=LoopDecision.CONTINUE_SAME_HYPOTHESIS,
        reason=f"Continuing with signal: {directional_signal}",
    )


def _pivot_or_regenerate(
    portfolio_has_alternatives: bool,
    regeneration_attempted: bool,
    autonomy_policy: AutonomyPolicyConfig,
    reason: str,
) -> LoopDecisionResult:
    """Pivot to next hypothesis, regenerate portfolio, or escalate."""
    if portfolio_has_alternatives:
        return LoopDecisionResult(
            decision=LoopDecision.PIVOT_HYPOTHESIS,
            reason=reason,
        )
    if (
        autonomy_policy.auto_regenerate_hypotheses
        and not regeneration_attempted
    ):
        return LoopDecisionResult(
            decision=LoopDecision.REGENERATE_PORTFOLIO,
            reason=f"{reason}; no alternatives — regenerating portfolio",
        )
    if autonomy_policy.escalate_on_portfolio_exhausted:
        return LoopDecisionResult(
            decision=LoopDecision.ESCALATE,
            reason=f"{reason}; portfolio exhausted",
        )
    return LoopDecisionResult(
        decision=LoopDecision.BUDGET_EXHAUSTED,
        reason=f"{reason}; portfolio exhausted, escalation disabled",
    )
