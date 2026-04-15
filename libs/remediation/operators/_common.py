"""Shared helpers for Phase 4 remediation operators."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.services.job_service import create_job
from libs.execution.operators._common import (
    ExecutionStateError,
    load_run_record,
    run_record_id_from_payload,
)
from libs.storage.models.experiment import ExperimentSpec, RunRecord
from libs.storage.models.remediation import MetricFrontier, RemediationAction

__all__ = [
    "ExecutionStateError",
    "enqueue_next_phase4",
    "load_lineage_actions",
    "load_lineage_run_ids",
    "load_run_record",
    "run_record_id_from_payload",
]


def enqueue_next_phase4(
    session: Session,
    *,
    cycle_id: UUID,
    next_job_type: str,
    run_record_id: UUID,
    extra_payload: dict | None = None,
) -> UUID:
    """Insert the next Phase 4 operator job and return its id."""
    payload: dict = {"run_record_id": str(run_record_id)}
    if extra_payload:
        payload.update(extra_payload)
    job = create_job(
        session,
        cycle_id=cycle_id,
        job_type=next_job_type,
        payload=payload,
        priority=10,
    )
    return job.id


def count_lineage_attempts(session: Session, run_id: UUID) -> int:
    """Count the number of remediation attempts in a run's lineage.

    Walks the parent_run_id chain backwards and counts RemediationAction
    rows linked to any run in the chain.
    """
    return len(load_lineage_actions(session, run_id))


def load_lineage_run_ids(session: Session, run_id: UUID) -> list[UUID]:
    """Return the current retry lineage from root to *run_id*.

    This walks only the active ancestor chain. It does not include sibling
    retries or descendants from other branches.
    """
    lineage_ids: list[UUID] = []
    current_id: UUID | None = run_id

    while current_id is not None:
        lineage_ids.append(current_id)
        run = session.get(RunRecord, current_id)
        if run is None:
            break
        current_id = run.parent_run_id

    lineage_ids.reverse()
    return lineage_ids


def load_lineage_actions(session: Session, run_id: UUID) -> list[RemediationAction]:
    """Load remediation actions for the active retry lineage of *run_id*."""
    lineage_ids = load_lineage_run_ids(session, run_id)
    if not lineage_ids:
        return []
    return list(
        session.execute(
            select(RemediationAction)
            .where(RemediationAction.run_record_id.in_(lineage_ids))
            .order_by(RemediationAction.created_at.asc())
        ).scalars().all()
    )


def load_experiment_spec(session: Session, spec_id: UUID) -> ExperimentSpec:
    """Load an experiment spec or raise."""
    spec = session.get(ExperimentSpec, spec_id)
    if spec is None:
        raise ExecutionStateError(f"experiment spec {spec_id} not found")
    return spec


def load_frontier(
    session: Session,
    charter_id: UUID,
    hypothesis_card_id: UUID,
) -> MetricFrontier | None:
    """Load the metric frontier for a hypothesis line, if one exists."""
    return session.execute(
        select(MetricFrontier).where(
            MetricFrontier.charter_id == charter_id,
            MetricFrontier.hypothesis_card_id == hypothesis_card_id,
        )
    ).scalar_one_or_none()


def get_primary_metric(spec: ExperimentSpec) -> dict | None:
    """Get the primary metric dict from a spec, or None."""
    metrics = spec.metrics or []
    if not metrics:
        return None
    idx = spec.primary_metric_index or 0
    if idx >= len(metrics):
        idx = 0
    return metrics[idx]
