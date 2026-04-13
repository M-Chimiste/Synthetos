"""Metric frontier upsert logic.

Maintains best-known metric state per hypothesis line (charter + hypothesis card).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.storage.models.remediation import MetricFrontier


def upsert_frontier(
    db: Session,
    *,
    charter_id: UUID,
    hypothesis_card_id: UUID,
    experiment_spec_id: UUID,
    run_id: UUID,
    metric_name: str,
    metric_direction: str,
    metric_value: float,
    is_successful: bool,
) -> tuple[MetricFrontier, bool]:
    """Create or update the metric frontier for a hypothesis line.

    Returns:
        A tuple of (frontier, improved) where improved is True if
        the frontier best value was updated.
    """
    frontier = db.execute(
        select(MetricFrontier).where(
            MetricFrontier.charter_id == charter_id,
            MetricFrontier.hypothesis_card_id == hypothesis_card_id,
        )
    ).scalar_one_or_none()

    now = utcnow()

    if frontier is None:
        frontier = MetricFrontier(
            id=uuid7(),
            charter_id=charter_id,
            hypothesis_card_id=hypothesis_card_id,
            primary_metric_name=metric_name,
            primary_metric_direction=metric_direction,
            best_run_id=run_id,
            best_experiment_spec_id=experiment_spec_id,
            best_metric_value=metric_value,
            best_achieved_at=now,
            total_runs=1,
            successful_runs=1 if is_successful else 0,
            runs_since_improvement=0,
            updated_at=now,
            created_at=now,
        )
        db.add(frontier)
        return frontier, True

    frontier.total_runs += 1
    if is_successful:
        frontier.successful_runs += 1

    is_better = _is_improvement(metric_value, frontier.best_metric_value, metric_direction)

    if is_better and is_successful:
        frontier.best_run_id = run_id
        frontier.best_experiment_spec_id = experiment_spec_id
        frontier.best_metric_value = metric_value
        frontier.best_achieved_at = now
        frontier.runs_since_improvement = 0
    else:
        frontier.runs_since_improvement += 1

    frontier.updated_at = now
    return frontier, is_better and is_successful


def _is_improvement(current: float, best: float, direction: str) -> bool:
    """Check if the current value improves on the best known value."""
    if direction == "maximize":
        return current > best
    return current < best
