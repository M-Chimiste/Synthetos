"""Shared helpers for verification operators."""

from __future__ import annotations

from uuid import UUID

from libs.core.services.job_service import create_job
from libs.execution.operators._common import (
    ExecutionStateError,
    load_run_record,
    run_record_id_from_payload,
)

__all__ = [
    "ExecutionStateError",
    "load_run_record",
    "run_record_id_from_payload",
]


def enqueue_next_verification(
    session,
    *,
    cycle_id: UUID,
    next_job_type: str,
    run_record_id: UUID,
) -> UUID:
    """Insert the next verification operator job and return its id."""
    job = create_job(
        session,
        cycle_id=cycle_id,
        job_type=next_job_type,
        payload={"run_record_id": str(run_record_id)},
        priority=10,
    )
    return job.id
