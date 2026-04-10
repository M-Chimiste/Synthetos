"""Synchronous job queue operations for the worker runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text, update
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.types import JobStatus
from libs.storage.models.jobs import Job

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session


def create_job(
    session: Session,
    *,
    cycle_id: UUID | None = None,
    job_type: str,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
) -> Job:
    """Insert a new pending job into the queue."""
    job = Job(
        id=uuid7(),
        cycle_id=cycle_id,
        job_type=job_type,
        status=JobStatus.pending,
        payload=payload,
        priority=priority,
        created_at=utcnow(),
    )
    session.add(job)
    session.flush()
    return job


def claim_job(session: Session, worker_id: str) -> Job | None:
    """Claim the highest-priority pending job using SELECT ... FOR UPDATE SKIP LOCKED.

    Returns the claimed Job row, or None if no work is available.
    """
    now = utcnow()
    result = session.execute(
        text("""
            UPDATE jobs
            SET status = :claimed, claimed_by = :worker_id, claimed_at = :now
            WHERE id = (
                SELECT id FROM jobs
                WHERE status = :pending
                ORDER BY priority DESC, created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
        """),
        {
            "claimed": JobStatus.claimed.value,
            "worker_id": worker_id,
            "now": now,
            "pending": JobStatus.pending.value,
        },
    )
    row = result.mappings().first()
    if row is None:
        return None

    session.commit()
    # Re-fetch via ORM so caller gets a proper Job instance.
    job = session.get(Job, row["id"])
    return job


def complete_job(
    session: Session,
    job_id: UUID,
    result: dict[str, Any] | None = None,
) -> Job:
    """Mark a job as completed with an optional result payload."""
    now = utcnow()
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status=JobStatus.completed,
            result=result,
            completed_at=now,
        )
    )
    session.commit()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after completion"
    return job


def fail_job(
    session: Session,
    job_id: UUID,
    error: str,
) -> Job:
    """Mark a job as failed with an error message."""
    now = utcnow()
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status=JobStatus.failed,
            error=error,
            completed_at=now,
        )
    )
    session.commit()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after failure"
    return job


def heartbeat_job(session: Session, job_id: UUID) -> None:
    """Update the heartbeat timestamp for a running job."""
    session.execute(update(Job).where(Job.id == job_id).values(heartbeat_at=utcnow()))
    session.commit()
