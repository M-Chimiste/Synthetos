"""Deterministic verification recommendations and rerun guidance."""

from __future__ import annotations

from typing import Any

OUTCOME_ORDER = {
    "invalid": 0,
    "rejected": 1,
    "tentative": 2,
    "robust": 3,
}


def build_rerun_note(
    *,
    outcome: str,
    run_status: str,
    baseline_comparison: dict[str, Any],
    historical_comparisons: list[dict[str, Any]],
    output_contract_checks: list[dict[str, Any]],
    metric_sanity_checks: list[dict[str, Any]],
    directional_signal: str | None = None,
    self_critic_result: dict[str, Any] | None = None,
    tradeoff_resolution: dict[str, Any] | None = None,
) -> str | None:
    """Generate deterministic replay/rerun guidance from verification state."""
    self_critic_result = self_critic_result or {}
    tradeoff_resolution = tradeoff_resolution or {}
    if run_status == "failed":
        return (
            "Retry only after fixing the execution failure "
            "and regenerating the declared artifacts."
        )
    if self_critic_result.get("blocking"):
        critical_issues = [
            item.get("issue", "critical self-critic finding")
            for item in self_critic_result.get("flags", [])
            if item.get("severity") == "critical"
        ]
        issue_text = critical_issues[0] if critical_issues else "critical self-critic finding"
        return f"Rerun only after addressing the blocking self-critic issue: {issue_text}."
    if any(not item.get("passed", True) for item in output_contract_checks):
        return (
            "Rerun after fixing the output contract mismatch so "
            "declared artifacts are produced and parseable."
        )
    if any(not item.get("passed", True) for item in metric_sanity_checks):
        return (
            "Rerun after fixing metric generation or validation so "
            "the reported metrics satisfy the spec bounds."
        )
    if outcome == "tentative":
        if directional_signal == "stalled":
            return (
                "Metric trend is stalled; consider a different approach "
                "or parameter variation rather than rerunning the same protocol."
            )
        if not historical_comparisons:
            return (
                "Replay or rerun once more to establish "
                "same-charter comparison history before promotion."
            )
        delta_pct = baseline_comparison.get("delta_pct")
        if isinstance(delta_pct, (int, float)) and abs(delta_pct) < 1.0:
            return "Rerun or replay to confirm the marginal improvement before promotion."
    if tradeoff_resolution.get("resolution") == "needs_investigation":
        return (
            tradeoff_resolution.get("recommendation")
            or "Run a follow-up experiment to understand the metric tradeoff."
        )
    return None


def build_next_step_recommendations(
    *,
    outcome: str,
    min_outcome_for_promotion: str,
    rerun_note: str | None,
    retrieval_hints: list[dict[str, Any]] | None = None,
    protocol_update_hints: list[dict[str, Any]] | None = None,
    reviewer_summary: str | None = None,
    directional_signal: str | None = None,
    tradeoff_resolution: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return structured recommendations for orchestrators and UI clients."""
    recommendations: list[dict[str, Any]] = []
    retrieval_hints = retrieval_hints or []
    protocol_update_hints = protocol_update_hints or []
    tradeoff_resolution = tradeoff_resolution or {}

    if OUTCOME_ORDER.get(outcome, 0) >= OUTCOME_ORDER.get(min_outcome_for_promotion, 0):
        recommendations.append({
            "recommendation_type": "promote_result",
            "rationale": (
                reviewer_summary
                or "Verification meets the configured promotion threshold."
            ),
            "payload": {"minimum_required_outcome": min_outcome_for_promotion},
        })
    elif outcome == "tentative":
        recommendations.append({
            "recommendation_type": "replay_or_retry",
            "rationale": rerun_note or "Verification is tentative and needs more confirmation.",
            "payload": {"recommended_skills": ["verification.verification_summary"]},
        })
    elif outcome == "rejected":
        recommendations.append({
            "recommendation_type": "revise_protocol",
            "rationale": (
                "Verification rejected the result; revise the protocol "
                "before another run."
            ),
            "payload": {
                "suggested_fields": [
                    item.get("field")
                    for item in protocol_update_hints
                    if item.get("field")
                ],
                "recommended_skills": ["verification.postmortem_reflection"],
            },
        })
    else:
        recommendations.append({
            "recommendation_type": "retry_run",
            "rationale": (
                rerun_note
                or "The run is invalid and should be retried only after remediation."
            ),
            "payload": {"recommended_skills": ["verification.run_evaluator"]},
        })

    if retrieval_hints:
        recommendations.append({
            "recommendation_type": "follow_up_search",
            "rationale": (
                "Failure memory suggests targeted literature "
                "follow-up before the next attempt."
            ),
            "payload": {
                "queries": [
                    item.get("query")
                    for item in retrieval_hints
                    if item.get("query")
                ],
            },
        })

    if protocol_update_hints:
        recommendations.append({
            "recommendation_type": "protocol_revision",
            "rationale": (
                "Verification and postmortem hints point to concrete "
                "protocol adjustments."
            ),
            "payload": {"updates": protocol_update_hints},
        })

    # Directional signal recommendations
    if directional_signal == "advancing":
        recommendations.append({
            "recommendation_type": "intensify_approach",
            "rationale": "Primary metric is advancing. Continue this approach.",
            "payload": {},
        })
    elif directional_signal == "stalled":
        recommendations.append({
            "recommendation_type": "stall_alert",
            "rationale": (
                "Primary metric is stalled across recent runs. "
                "Consider a parameter sweep or hypothesis pivot."
            ),
            "payload": {},
        })
    elif directional_signal == "regressing":
        recommendations.append({
            "recommendation_type": "regression_warning",
            "rationale": (
                "Primary metric is regressing. Consider reverting to "
                "the best known configuration or trying a different approach."
            ),
            "payload": {},
        })
    elif directional_signal == "noisy":
        recommendations.append({
            "recommendation_type": "noise_alert",
            "rationale": (
                "Metric trend is noisy with no clear direction. "
                "Run more experiments for statistical power."
            ),
            "payload": {},
        })
    elif directional_signal == "breakthrough":
        recommendations.append({
            "recommendation_type": "breakthrough_flag",
            "rationale": (
                "Large unexpected improvement detected. "
                "This result warrants attention and potential fast-track promotion."
            ),
            "payload": {},
        })

    resolution = tradeoff_resolution.get("resolution")
    if resolution == "reject_tradeoff":
        recommendations.append({
            "recommendation_type": "tradeoff_pivot",
            "rationale": (
                tradeoff_resolution.get("rationale")
                or "Constraint regressions outweigh the primary metric improvement."
            ),
            "payload": {"recommendation": tradeoff_resolution.get("recommendation")},
        })
    elif resolution == "needs_investigation":
        recommendations.append({
            "recommendation_type": "investigate_tradeoff",
            "rationale": (
                tradeoff_resolution.get("rationale")
                or "The metric tradeoff is ambiguous and needs more evidence."
            ),
            "payload": {"recommendation": tradeoff_resolution.get("recommendation")},
        })
    elif resolution == "accept_tradeoff":
        recommendations.append({
            "recommendation_type": "continue_with_guardrails",
            "rationale": (
                tradeoff_resolution.get("rationale")
                or "The current tradeoff is acceptable, but the constraint should stay monitored."
            ),
            "payload": {"recommendation": tradeoff_resolution.get("recommendation")},
        })

    return recommendations
