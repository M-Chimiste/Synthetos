from __future__ import annotations

import signal
import threading

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from libs.core.config import AppConfig
from libs.core.policy import Actor
from libs.core.state_machine import CycleStatus
from libs.orchestration.job_queue import (
    claim_next_job,
    cycle_for_job,
    mark_job_failed,
    mark_job_succeeded,
    reclaim_expired_leases,
)
from libs.orchestration.operators import OPERATOR_REGISTRY
from libs.storage.models import JobModel
from libs.storage.services import (
    append_event,
    apply_operator_result,
    create_state_snapshot,
)

log = structlog.get_logger(__name__)

_shutdown_event = threading.Event()


def _has_pending_jobs(session: Session, cycle_id: int) -> bool:
    job = session.scalar(
        select(JobModel).where(
            JobModel.cycle_id == cycle_id,
            JobModel.status.in_(["pending", "claimed"]),
        )
    )
    return job is not None


def run_worker_once(
    session: Session, config: AppConfig, actor: Actor,
) -> str:
    job = claim_next_job(session, worker_id=actor.actor_id)
    if job is None:
        return "no_job"
    cycle = cycle_for_job(session, job)
    if cycle is None:
        mark_job_failed(session, job, "Job has no cycle")
        return "job_failed"
    not_runnable = {
        CycleStatus.PAUSED.value,
        CycleStatus.CANCEL_REQUESTED.value,
        CycleStatus.CANCELLED.value,
    }
    if cycle.current_status in not_runnable:
        mark_job_failed(
            session, job,
            f"Cycle not runnable in status {cycle.current_status}",
        )
        return "cycle_not_runnable"

    create_state_snapshot(
        session,
        cycle=cycle,
        target_state=CycleStatus.INITIALIZING,
        actor=actor,
        reason=f"Worker claimed job {job.public_id}",
        context={"job_public_id": job.public_id},
    )
    if job.operator_name == "run_execute":
        create_state_snapshot(
            session,
            cycle=cycle,
            target_state=CycleStatus.RUNNING,
            actor=actor,
            reason=f"Run execution started for job {job.public_id}",
            context={"job_public_id": job.public_id},
        )
    append_event(
        session,
        actor=actor,
        event_type="job_claimed",
        payload={
            "job_public_id": job.public_id,
            "operator_name": job.operator_name,
        },
        cycle_id=cycle.id,
        job_id=job.id,
    )
    operator = OPERATOR_REGISTRY[job.operator_name]
    log.info(
        "operator_starting",
        job_id=job.public_id,
        cycle_id=cycle.public_id,
        operator=job.operator_name,
    )
    try:
        result = operator(session, config, actor, cycle, job)
        apply_operator_result(
            session, cycle=cycle, job=job,
            actor=actor, result=result, config=config,
        )
        mark_job_succeeded(session, job)
        # If next_actions enqueued new jobs, ensure cycle is QUEUED so they run
        if result.next_actions and _has_pending_jobs(session, cycle.id):
            current = CycleStatus(cycle.current_status)
            if current == CycleStatus.READY:
                create_state_snapshot(
                    session,
                    cycle=cycle,
                    target_state=CycleStatus.QUEUED,
                    actor=actor,
                    reason="Auto-queued for next pipeline step",
                    context={"next_operator": result.next_actions[0].action},
                )
        log.info(
            "operator_succeeded",
            job_id=job.public_id,
            cycle_id=cycle.public_id,
            operator=job.operator_name,
        )
        return "job_succeeded"
    except Exception as exc:
        log.error(
            "operator_failed",
            job_id=job.public_id,
            cycle_id=cycle.public_id,
            operator=job.operator_name,
            error=str(exc),
        )
        cycle.last_error = str(exc)
        if cycle.current_status != CycleStatus.FAILED.value:
            create_state_snapshot(
                session,
                cycle=cycle,
                target_state=CycleStatus.FAILED,
                actor=actor,
                reason="Operator failed",
                context={"error": str(exc)},
            )
        append_event(
            session,
            actor=actor,
            event_type="job_failed",
            payload={
                "job_public_id": job.public_id,
                "error": str(exc),
            },
            cycle_id=cycle.id,
            job_id=job.id,
        )
        mark_job_failed(session, job, str(exc))
        return "job_failed"


def run_worker_forever(
    session_factory: sessionmaker[Session],
    config: AppConfig,
    actor: Actor,
) -> None:
    _shutdown_event.clear()

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("shutdown_requested", signal=signum)
        _shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Reclaim any jobs left by crashed workers
    with session_factory() as session:
        reclaimed = reclaim_expired_leases(session)
        session.commit()
        if reclaimed:
            log.info("reclaimed_expired_leases", count=reclaimed)

    log.info("worker_started")
    while not _shutdown_event.is_set():
        with session_factory() as session:
            result = run_worker_once(session, config, actor)
            session.commit()
        if result == "no_job":
            _shutdown_event.wait(timeout=1.0)
    log.info("worker_stopped")
