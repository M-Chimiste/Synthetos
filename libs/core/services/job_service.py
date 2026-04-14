"""Synchronous job queue operations for the worker runtime."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select, text, update
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import JobLifecycleEvents
from libs.core.events import emit_event_sync
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


def get_job(session: Session, job_id: UUID) -> Job | None:
    """Fetch a job by ID using the current session."""
    return session.get(Job, job_id)


def start_job(session: Session, job_id: UUID) -> Job:
    """Mark a claimed job as running."""
    session.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.running))
    session.flush()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after start"
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
    session.flush()
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
    session.flush()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after failure"
    return job


def heartbeat_job(session: Session, job_id: UUID) -> None:
    """Update the heartbeat timestamp for a running job."""
    session.execute(update(Job).where(Job.id == job_id).values(heartbeat_at=utcnow()))
    session.commit()


def pause_job(session: Session, job_id: UUID, *, result: dict[str, Any] | None = None) -> Job:
    """Mark a job as paused and optionally store the latest result snapshot."""
    values: dict[str, Any] = {"status": JobStatus.paused}
    if result is not None:
        values["result"] = result

    session.execute(update(Job).where(Job.id == job_id).values(**values))
    session.flush()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after pause"
    return job


def reclaim_stale_jobs(
    session: Session,
    *,
    heartbeat_timeout_s: int,
    max_reclaims: int = 3,
) -> dict[str, int]:
    """Reset stale ``claimed``/``running`` jobs back to ``pending``.

    A job is stale when its ``heartbeat_at`` (or ``claimed_at`` if no heartbeat
    yet) is older than ``heartbeat_timeout_s`` seconds. After ``max_reclaims``
    reclaims on the same job, it is moved to ``failed`` instead.

    Returns a dict with ``reclaimed`` and ``failed_exhausted`` counts. Emits a
    ``job.reclaimed`` or ``job.reclaim_exhausted`` event per affected row.
    Commits the session before returning so the worker never double-claims.
    """
    now = utcnow()
    cutoff = now - timedelta(seconds=heartbeat_timeout_s)

    stmt = (
        select(Job)
        .where(Job.status.in_([JobStatus.claimed, JobStatus.running]))
        .where(
            or_(
                Job.heartbeat_at.is_(None) & (Job.claimed_at < cutoff),
                Job.heartbeat_at < cutoff,
            )
        )
    )
    stale_jobs = session.execute(stmt).scalars().all()

    reclaimed = 0
    exhausted = 0
    for job in stale_jobs:
        next_count = int(job.reclaim_count or 0) + 1
        if next_count > max_reclaims:
            job.status = JobStatus.failed
            job.error = (
                f"reclaim_exhausted after {job.reclaim_count} reclaims "
                f"(heartbeat_timeout_s={heartbeat_timeout_s})"
            )
            job.completed_at = now
            emit_event_sync(
                session,
                event_type=JobLifecycleEvents.reclaim_exhausted.value,
                cycle_id=job.cycle_id,
                payload={
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "reclaim_count": job.reclaim_count,
                },
            )
            exhausted += 1
        else:
            job.status = JobStatus.pending
            job.claimed_by = None
            job.claimed_at = None
            job.heartbeat_at = None
            job.reclaim_count = next_count
            emit_event_sync(
                session,
                event_type=JobLifecycleEvents.reclaimed.value,
                cycle_id=job.cycle_id,
                payload={
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "reclaim_count": next_count,
                    "heartbeat_timeout_s": heartbeat_timeout_s,
                },
            )
            reclaimed += 1

    if stale_jobs:
        session.commit()
    return {"reclaimed": reclaimed, "failed_exhausted": exhausted}


def resume_job(session: Session, job_id: UUID) -> Job:
    """Resume a paused job by returning it to the pending queue."""
    session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(
            status=JobStatus.pending,
            claimed_by=None,
            claimed_at=None,
            heartbeat_at=None,
        )
    )
    session.flush()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after resume"
    return job
