from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.ids import generate_public_id
from libs.core.policy import Actor
from libs.core.state_machine import CycleStatus
from libs.storage.models import JobModel, ResearchCycleModel
from libs.storage.services import append_event


def enqueue_job(
    session: Session,
    actor: Actor,
    cycle_id: int | None,
    operator_name: str,
    payload: dict,
    max_attempts: int = 3,
) -> JobModel:
    job = JobModel(
        public_id=generate_public_id("job"),
        cycle_id=cycle_id,
        operator_name=operator_name,
        status="pending",
        payload=payload,
        attempts=0,
        max_attempts=max_attempts,
    )
    session.add(job)
    session.flush()
    append_event(
        session,
        actor=actor,
        event_type="job_enqueued",
        payload={"job_public_id": job.public_id, "operator_name": operator_name},
        cycle_id=cycle_id,
        job_id=job.id,
    )
    return job


def claim_next_job(
    session: Session,
    worker_id: str,
    lease_minutes: int = 5,
) -> JobModel | None:
    now = datetime.now(UTC)
    job = session.scalar(
        select(JobModel)
        .where(JobModel.status == "pending", JobModel.available_at <= now)
        .order_by(JobModel.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "claimed"
    job.attempts += 1
    job.claimed_by = worker_id
    job.started_at = now
    job.lease_expires_at = now + timedelta(minutes=lease_minutes)
    session.flush()
    return job


def mark_job_succeeded(session: Session, job: JobModel) -> None:
    job.status = "succeeded"
    job.finished_at = datetime.now(UTC)
    job.lease_expires_at = None
    session.flush()


def mark_job_failed(session: Session, job: JobModel, error: str) -> None:
    now = datetime.now(UTC)
    job.last_error = error
    if job.attempts < job.max_attempts:
        job.status = "pending"
        backoff = 5 * (2 ** (job.attempts - 1))  # 5s, 10s, 20s
        job.available_at = now + timedelta(seconds=backoff)
        job.lease_expires_at = None
    else:
        job.status = "failed"
        job.finished_at = now
        job.lease_expires_at = None
    session.flush()


def reclaim_expired_leases(session: Session) -> int:
    """Reset jobs with expired leases back to pending and mark affected cycles as FAILED."""
    now = datetime.now(UTC)
    stale = session.scalars(
        select(JobModel).where(
            JobModel.status == "claimed",
            JobModel.lease_expires_at <= now,
        )
    ).all()
    affected_cycle_ids: set[int] = set()
    for job in stale:
        job.status = "pending"
        job.claimed_by = None
        job.lease_expires_at = None
        if job.cycle_id is not None:
            affected_cycle_ids.add(job.cycle_id)
    # Mark cycles that were in active states as FAILED due to lease expiry
    active_statuses = {
        CycleStatus.RUNNING.value,
        CycleStatus.INITIALIZING.value,
        CycleStatus.RESUMING.value,
    }
    for cycle_id in affected_cycle_ids:
        cycle = session.get(ResearchCycleModel, cycle_id)
        if cycle is not None and cycle.current_status in active_statuses:
            cycle.current_status = CycleStatus.FAILED.value
            cycle.last_error = "Worker lease expired — cycle marked failed for recovery"
    session.flush()
    return len(stale)


def cycle_for_job(session: Session, job: JobModel) -> ResearchCycleModel | None:
    if job.cycle_id is None:
        return None
    return session.get(ResearchCycleModel, job.cycle_id)
