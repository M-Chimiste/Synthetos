"""Synchronous job queue operations for the worker runtime."""

from __future__ import annotations

import random
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select, text, update
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.event_types import JobLifecycleEvents
from libs.core.events import emit_event_sync
from libs.core.types import JobStatus
from libs.storage.models.jobs import Job

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session

# Crash-looped reclaims requeue with a short delay so a worker that dies on a
# specific job doesn't spin on it.
_RECLAIM_REQUEUE_DELAY_S = 30

# Cap the per-attempt history kept inside error_detail.
_MAX_ATTEMPT_HISTORY = 10


def _resolve_max_attempts(job_type: str) -> int:
    settings = get_settings()
    return int(settings.job_max_attempts_overrides.get(job_type, settings.job_default_max_attempts))


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
        max_attempts=_resolve_max_attempts(job_type),
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
                  AND (not_before IS NULL OR not_before <= :now)
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
    session.execute(
        update(Job).where(Job.id == job_id).values(status=JobStatus.running, started_at=utcnow())
    )
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
    *,
    error_detail: dict[str, Any] | None = None,
) -> Job:
    """Mark a job as failed with an error message and optional structured detail."""
    now = utcnow()
    values: dict[str, Any] = {
        "status": JobStatus.failed,
        "error": error,
        "completed_at": now,
    }
    if error_detail is not None:
        values["error_detail"] = error_detail
    session.execute(update(Job).where(Job.id == job_id).values(**values))
    session.flush()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after failure"
    return job


def _attempt_history(job: Job, entry: dict[str, Any]) -> dict[str, Any]:
    """Merge an attempt summary into the job's error_detail history."""
    detail = dict(job.error_detail or {})
    attempts = list(detail.get("attempts") or [])
    attempts.append(entry)
    detail["attempts"] = attempts[-_MAX_ATTEMPT_HISTORY:]
    return detail


def retry_or_fail_job(
    session: Session,
    job_id: UUID,
    *,
    error: str,
    error_detail: dict[str, Any] | None,
    retryable: bool,
) -> Job:
    """Requeue a failed job with backoff, or fail it when attempts are spent.

    The attempt that just failed becomes ``attempt_count + 1``. While attempts
    remain and the failure is retryable, the job returns to ``pending`` with
    ``not_before = now + min(cap, base * 2^failed_attempts) * jitter``. The
    caller commits (service convention). Check ``job.status`` to branch.
    """
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found for retry"

    settings = get_settings()
    failed_attempts = int(job.attempt_count or 0) + 1
    attempt_entry = {
        "attempt": failed_attempts,
        "error": error[:500],
        "error_class": (error_detail or {}).get("error_class"),
        "occurred_at": utcnow().isoformat(),
    }
    merged_detail = _attempt_history(job, attempt_entry)
    if error_detail:
        merged_detail.update(
            {key: value for key, value in error_detail.items() if key != "attempts"}
        )

    if not retryable or failed_attempts >= int(job.max_attempts or 1):
        return fail_job(session, job_id, error, error_detail=merged_detail)

    backoff = min(
        settings.job_retry_backoff_cap_s,
        settings.job_retry_backoff_base_s * (2 ** (failed_attempts - 1)),
    )
    backoff = int(backoff * random.uniform(0.8, 1.2))
    job.status = JobStatus.pending
    job.attempt_count = failed_attempts
    job.not_before = utcnow() + timedelta(seconds=backoff)
    job.error = error
    job.error_detail = merged_detail
    job.claimed_by = None
    job.claimed_at = None
    job.heartbeat_at = None
    job.started_at = None
    session.flush()
    return job


def cancel_job_record(
    session: Session,
    job_id: UUID,
    *,
    error_detail: dict[str, Any] | None = None,
) -> Job:
    """Mark a job cancelled (user intent honored) and clear the request flag."""
    values: dict[str, Any] = {
        "status": JobStatus.cancelled,
        "cancel_requested": False,
        "completed_at": utcnow(),
    }
    if error_detail is not None:
        values["error_detail"] = error_detail
    session.execute(update(Job).where(Job.id == job_id).values(**values))
    session.flush()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after cancel"
    return job


def heartbeat_job(session: Session, job_id: UUID) -> tuple[str | None, bool]:
    """Update the heartbeat timestamp; return (status, cancel_requested).

    The status/flag ride back on the same round-trip so the job supervisor
    can observe cancellation without a second query.
    """
    result = session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(heartbeat_at=utcnow())
        .returning(Job.status, Job.cancel_requested)
    )
    row = result.first()
    session.commit()
    if row is None:
        return None, False
    return str(row[0]), bool(row[1])


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
    cancelled = 0
    for job in stale_jobs:
        if job.cancel_requested:
            # The worker died before honoring a cancel; the user's intent stands.
            job.status = JobStatus.cancelled
            job.cancel_requested = False
            job.completed_at = now
            emit_event_sync(
                session,
                event_type="job_cancelled_acknowledged",
                cycle_id=job.cycle_id,
                payload={"job_id": str(job.id), "job_type": job.job_type, "via": "reclaim"},
            )
            cancelled += 1
            continue
        next_count = int(job.reclaim_count or 0) + 1
        if next_count > max_reclaims:
            job.status = JobStatus.failed
            job.error = (
                f"reclaim_exhausted after {job.reclaim_count} reclaims "
                f"(heartbeat_timeout_s={heartbeat_timeout_s})"
            )
            job.error_detail = {
                **(job.error_detail or {}),
                "error_class": "reclaim_exhausted",
                "reclaim_count": job.reclaim_count,
            }
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
            job.started_at = None
            # Short delay damps hot crash-loops on a poison job.
            job.not_before = now + timedelta(seconds=_RECLAIM_REQUEUE_DELAY_S)
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
    return {"reclaimed": reclaimed, "failed_exhausted": exhausted, "cancelled": cancelled}


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
            started_at=None,
            not_before=None,
            cancel_requested=False,
        )
    )
    session.flush()
    job = session.get(Job, job_id)
    assert job is not None, f"Job {job_id} not found after resume"
    return job
