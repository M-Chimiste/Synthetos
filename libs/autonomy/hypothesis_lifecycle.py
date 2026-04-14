"""Hypothesis lifecycle status transitions for the autonomous loop.

Phase 3 statuses (managed by ideation/compile operators):
  candidate, selected, compiled, rejected, deferred

Phase 5 statuses (managed by loop_decide via direct ORM writes):
  active, promising, stalled, deprioritized, validated
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from libs.core.clock import utcnow
from libs.core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from libs.storage.models.experiment import ExperimentSpec, HypothesisCard
    from libs.storage.models.remediation import MetricFrontier

log = get_logger("autonomy.hypothesis_lifecycle")

# Runs without improvement before a hypothesis is considered stalled
STALL_THRESHOLD = 5

# Valid Phase 5 transitions: {from_status: [to_statuses]}
_VALID_TRANSITIONS: dict[str, list[str]] = {
    "compiled": ["active"],
    "active": ["promising", "stalled", "deprioritized"],
    "promising": ["stalled", "validated"],
    "stalled": ["deprioritized"],
    "deferred": ["active"],
}


def compute_lifecycle_status(
    current_status: str,
    signal: str | None,
    frontier: MetricFrontier | None,
    recommendation_type: str,
    spec: ExperimentSpec | None = None,
) -> str | None:
    """Compute the target lifecycle status based on signal, frontier, and recommendation.

    Returns the new status, or None if no transition should occur.
    """
    allowed = _VALID_TRANSITIONS.get(current_status, [])
    if not allowed:
        return None

    # Entry: compiled -> active on first loop iteration
    if current_status in ("compiled", "deferred") and "active" in allowed:
        return "active"

    # Deprioritize on pivot recommendation
    if recommendation_type == "hypothesis_pivot" and "deprioritized" in allowed:
        return "deprioritized"

    # Check for validated (frontier meets stop_conditions)
    if (
        current_status == "promising"
        and "validated" in allowed
        and spec is not None
        and frontier is not None
    ):
        target = _check_stop_conditions(spec, frontier)
        if target:
            return "validated"

    # Check signal-driven transitions
    if signal in ("advancing", "breakthrough") and "promising" in allowed:
        return "promising"

    if (
        frontier is not None
        and frontier.runs_since_improvement >= STALL_THRESHOLD
        and "stalled" in allowed
    ):
        return "stalled"

    return None


def _check_stop_conditions(
    spec: ExperimentSpec, frontier: MetricFrontier
) -> bool:
    """Check if frontier meets the first stop condition's threshold."""
    stop_conditions = spec.stop_conditions or []
    if not stop_conditions:
        return False

    first = stop_conditions[0]
    if not isinstance(first, dict):
        return False

    threshold = first.get("threshold")
    if threshold is None:
        return False

    direction = frontier.primary_metric_direction
    best = frontier.best_metric_value
    if best is None:
        return False

    if direction == "maximize":
        return best >= threshold
    elif direction == "minimize":
        return best <= threshold

    return False


def update_hypothesis_status(
    session: Session,
    card: HypothesisCard,
    signal: str | None,
    frontier: MetricFrontier | None,
    recommendation_type: str,
    spec: ExperimentSpec | None = None,
) -> str:
    """Update the hypothesis card's lifecycle status if a valid transition exists.

    Returns the (possibly updated) status.
    """
    new_status = compute_lifecycle_status(
        card.status, signal, frontier, recommendation_type, spec
    )
    if new_status is not None and new_status != card.status:
        old_status = card.status
        card.status = new_status
        card.updated_at = utcnow()
        session.flush()
        log.info(
            "hypothesis_status_changed",
            card_id=str(card.id),
            from_status=old_status,
            to_status=new_status,
        )
    return card.status
