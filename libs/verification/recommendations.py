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
) -> str | None:
    """Generate deterministic replay/rerun guidance from verification state."""
    if run_status == "failed":
        return (
            "Retry only after fixing the execution failure "
            "and regenerating the declared artifacts."
        )
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
        if not historical_comparisons:
            return (
                "Replay or rerun once more to establish "
                "same-charter comparison history before promotion."
            )
        delta_pct = baseline_comparison.get("delta_pct")
        if isinstance(delta_pct, (int, float)) and abs(delta_pct) < 1.0:
            return "Rerun or replay to confirm the marginal improvement before promotion."
    return None


def build_next_step_recommendations(
    *,
    outcome: str,
    min_outcome_for_promotion: str,
    rerun_note: str | None,
    retrieval_hints: list[dict[str, Any]] | None = None,
    protocol_update_hints: list[dict[str, Any]] | None = None,
    reviewer_summary: str | None = None,
) -> list[dict[str, Any]]:
    """Return structured recommendations for orchestrators and UI clients."""
    recommendations: list[dict[str, Any]] = []
    retrieval_hints = retrieval_hints or []
    protocol_update_hints = protocol_update_hints or []

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

    return recommendations
