"""Shared helpers for execution operators."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.operators import OperatorInput
from libs.core.services.job_service import create_job
from libs.storage.models.experiment import RunRecord


class ExecutionStateError(Exception):
    """Raised when an execution operator cannot find the state it needs."""


def run_record_id_from_payload(op_input: OperatorInput) -> UUID:
    """Extract the run record id from a job payload."""
    raw = op_input.payload.get("run_record_id")
    if raw is None:
        raise ExecutionStateError(
            f"job {op_input.job_id} payload is missing required 'run_record_id'"
        )
    if isinstance(raw, UUID):
        return raw
    return UUID(str(raw))


def load_run_record(session: Session, run_id: UUID) -> RunRecord:
    """Load a run record or raise."""
    result = session.execute(select(RunRecord).where(RunRecord.id == run_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise ExecutionStateError(f"run record {run_id} not found")
    return obj


def enqueue_next(
    session: Session,
    *,
    cycle_id: UUID,
    next_job_type: str,
    run_record_id: UUID,
    extra_payload: dict | None = None,
) -> UUID:
    """Insert the next execution operator job and return its id."""
    payload = {"run_record_id": str(run_record_id)}
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
