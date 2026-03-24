"""Hypothesis status transitions for autonomous experiment loops."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from libs.storage.models import HypothesisCardModel

# Allowed status transitions for autonomous operation.
# Existing statuses (generated, critiqued, approved, compiled, rejected) are
# preserved; new autonomous statuses extend the lifecycle.
ALLOWED_HYPOTHESIS_TRANSITIONS: dict[str, set[str]] = {
    "generated": {"critiqued", "rejected"},
    "critiqued": {"approved", "rejected"},
    "approved": {"active", "rejected", "compiled"},
    "compiled": {"active"},
    "active": {"stalled", "deprioritized", "promising"},
    "stalled": {"active"},
    "deprioritized": set(),
    "promising": {"validated", "active"},
    "validated": set(),
    "rejected": set(),
}

# Statuses eligible for selection by the autonomous loop.
SELECTABLE_STATUSES = {"approved", "active", "promising"}

# Statuses excluded from portfolio re-ranking.
EXCLUDED_FROM_RANKING = {"stalled", "deprioritized", "validated", "rejected"}


def transition_hypothesis(
    session: Session,
    hypothesis: HypothesisCardModel,
    target_status: str,
    reason: str,
) -> None:
    """Apply a validated status transition to a hypothesis.

    Raises ValueError on invalid transition.
    """
    current = hypothesis.status
    allowed = ALLOWED_HYPOTHESIS_TRANSITIONS.get(current, set())
    if target_status not in allowed:
        msg = (
            f"Invalid hypothesis transition: "
            f"{current} -> {target_status}"
        )
        raise ValueError(msg)
    hypothesis.status = target_status
    hypothesis.ranking_rationale = (
        f"{hypothesis.ranking_rationale or ''}; "
        f"Transition to {target_status}: {reason}"
    ).lstrip("; ")
    session.flush()


def pick_next_hypothesis(
    session: Session,
    cycle_id: int,
    charter_id: int | None = None,
    exclude_hypothesis_id: int | None = None,
) -> HypothesisCardModel | None:
    """Select the top-ranked selectable hypothesis.

    Returns the highest-ranked hypothesis with status in
    SELECTABLE_STATUSES, excluding the optionally specified ID.
    """
    from libs.storage.models import HypothesisCardModel as HCM

    query = (
        select(HCM)
        .where(
            HCM.cycle_id == cycle_id,
            HCM.status.in_(list(SELECTABLE_STATUSES)),
        )
        .order_by(HCM.portfolio_rank.asc())
    )
    if exclude_hypothesis_id is not None:
        query = query.where(HCM.id != exclude_hypothesis_id)

    return session.scalar(query)
