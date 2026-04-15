"""Deterministic recommendation rules.

Maps (directional signal, frontier state, remediation history) to a
recommendation type and action text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecommendationResult:
    """Output of the recommendation decision logic."""

    recommendation_type: str
    action: str
    reasoning: str


@dataclass(frozen=True)
class RecommendationInputs:
    """Inputs to the recommendation decision logic."""

    signal: str | None  # None for failed runs
    runs_since_improvement: int
    total_runs: int
    successful_runs: int
    remediation_attempts: int
    remediation_exhausted: bool
    has_unresolved_failures: bool
    failed: bool  # True if this is a failed (exhausted) run path


# Staleness threshold: pivot after this many runs without improvement
STALL_THRESHOLD = 5


def compute_recommendation(inputs: RecommendationInputs) -> RecommendationResult:
    """Apply deterministic decision rules to produce a recommendation.

    The rules distinguish between:
    - mechanical_recovery: transient infrastructure issues
    - parameter_variation: same hypothesis, different controls/params
    - hypothesis_pivot: fundamental direction change needed
    - continue_current: current approach is working
    - halt: no viable path forward
    """
    # Failed run path (arrived via postmortem, no signal)
    if inputs.failed:
        if inputs.remediation_exhausted:
            if inputs.successful_runs == 0:
                return RecommendationResult(
                    recommendation_type="hypothesis_pivot",
                    action=(
                        "All runs failed and remediation is exhausted. "
                        "Consider a fundamentally different approach or hypothesis."
                    ),
                    reasoning=(
                        f"No successful runs out of {inputs.total_runs} total; "
                        f"{inputs.remediation_attempts} remediation attempts exhausted. "
                        "Mechanical issues appear intractable for this approach."
                    ),
                )
            return RecommendationResult(
                recommendation_type="parameter_variation",
                action=(
                    "Recent run failed after remediation. "
                    "Try adjusting experiment parameters to avoid this failure mode."
                ),
                reasoning=(
                    f"{inputs.successful_runs} prior successes exist but latest run "
                    f"failed after {inputs.remediation_attempts} remediation attempts. "
                    "The approach has worked before; parameter adjustments may help."
                ),
            )
        # Failed but remediation resolved it (shouldn't normally reach recommend
        # via this path, but handle gracefully)
        return RecommendationResult(
            recommendation_type="continue_current",
            action="Remediation resolved the failure. Continue with current approach.",
            reasoning="Failure was mechanical and has been resolved through remediation.",
        )

    # Successful run path (has signal)
    signal = inputs.signal

    if signal == "breakthrough":
        return RecommendationResult(
            recommendation_type="continue_current",
            action="Significant improvement detected. Continue with current approach.",
            reasoning=(
                "Metric showed breakthrough-level improvement. "
                "This approach is producing strong results."
            ),
        )

    if signal == "advancing":
        if inputs.has_unresolved_failures:
            return RecommendationResult(
                recommendation_type="parameter_variation",
                action=(
                    "Progress is being made but recurring failures suggest "
                    "parameter adjustments to improve reliability."
                ),
                reasoning=(
                    "Metric is advancing but there are unresolved failure patterns. "
                    "Tweaking parameters may reduce failure rate while maintaining progress."
                ),
            )
        return RecommendationResult(
            recommendation_type="continue_current",
            action="Metric is improving. Continue with current approach.",
            reasoning="Directional signal is advancing with no unresolved failures.",
        )

    if signal == "stalled":
        if inputs.runs_since_improvement >= STALL_THRESHOLD:
            return RecommendationResult(
                recommendation_type="hypothesis_pivot",
                action=(
                    f"No improvement in {inputs.runs_since_improvement} runs. "
                    "Consider a new hypothesis or fundamentally different approach."
                ),
                reasoning=(
                    f"Metric stalled for {inputs.runs_since_improvement} runs "
                    f"(threshold: {STALL_THRESHOLD}). Diminishing returns suggest "
                    "the current hypothesis has been exhausted."
                ),
            )
        return RecommendationResult(
            recommendation_type="parameter_variation",
            action=(
                "Metric has plateaued. Try different hyperparameters, "
                "controls, or training configurations."
            ),
            reasoning=(
                f"Metric stalled for {inputs.runs_since_improvement} runs "
                f"(below pivot threshold of {STALL_THRESHOLD}). "
                "Parameter variation may break through the plateau."
            ),
        )

    if signal == "regressing":
        return RecommendationResult(
            recommendation_type="parameter_variation",
            action=(
                "Metric is moving in the wrong direction. "
                "Revert recent changes or adjust parameters."
            ),
            reasoning=(
                "Directional signal shows regression. Recent modifications "
                "are hurting performance; parameter adjustments needed."
            ),
        )

    if signal == "noisy":
        return RecommendationResult(
            recommendation_type="parameter_variation",
            action=(
                "Metric is oscillating. Consider increasing sample size, "
                "fixing random seeds, or reducing learning rate."
            ),
            reasoning=(
                "Directional signal shows noise. High variance in metric "
                "suggests instability in the experimental setup."
            ),
        )

    # Fallback for unknown signals
    return RecommendationResult(
        recommendation_type="parameter_variation",
        action="Signal is ambiguous. Try parameter adjustments to clarify direction.",
        reasoning=f"Unrecognized signal '{signal}'; defaulting to parameter variation.",
    )
