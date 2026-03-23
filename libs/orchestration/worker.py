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
from libs.storage.models import JobModel, RunRecordModel
from libs.storage.services import (
    append_event,
    apply_operator_result,
    create_state_snapshot,
)

log = structlog.get_logger(__name__)

_shutdown_event = threading.Event()

# Operators that run without an associated research cycle.
CYCLE_INDEPENDENT_OPERATORS: set[str] = {"arxiv_warehouse_sync"}

# Operator pipelines: ordered sequences for resume logic.
# Each pipeline maps to a sequence of operators that run in order.
OPERATOR_PIPELINES: dict[str, list[str]] = {
    "explore": [
        "initialize_cycle",
        "source_retrieval",
        "literature_screen",
        "shortlist_rank",
        "fulltext_escalation",
        "literature_report",
    ],
    "ideation": [
        "evidence_extraction",
        "hypothesis_generation",
        "hypothesis_critique",
        "protocol_compilation",
    ],
    "execution": [
        "run_prepare",
        "run_execute",
        "run_finalize",
    ],
    "verification": [
        "run_verify",
        "failure_postmortem",
        "verification_report",
    ],
}


def next_operator_after(completed: str) -> str | None:
    """Given the last completed operator, return the next one in its pipeline."""
    for pipeline in OPERATOR_PIPELINES.values():
        if completed in pipeline:
            idx = pipeline.index(completed)
            if idx + 1 < len(pipeline):
                return pipeline[idx + 1]
            return None
    return None


def _has_pending_jobs(session: Session, cycle_id: int) -> bool:
    job = session.scalar(
        select(JobModel).where(
            JobModel.cycle_id == cycle_id,
            JobModel.status.in_(["pending", "claimed"]),
        )
    )
    return job is not None


def _run_for_job(session: Session, job: JobModel) -> RunRecordModel | None:
    run_public_id = (job.payload or {}).get("run_public_id")
    if not run_public_id:
        return None
    return session.scalar(
        select(RunRecordModel).where(RunRecordModel.public_id == run_public_id)
    )


def run_worker_once(
    session: Session, config: AppConfig, actor: Actor,
) -> str:
    job = claim_next_job(session, worker_id=actor.actor_id)
    if job is None:
        return "no_job"

    # Cycle-independent operators skip all cycle state checks
    if job.operator_name in CYCLE_INDEPENDENT_OPERATORS:
        return _run_cycle_independent_job(session, config, actor, job)

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

    # Handle RESUMING state: transition to appropriate active state
    if cycle.current_status == CycleStatus.RESUMING.value:
        run = _run_for_job(session, job)
        resumed_from = (
            run.last_completed_operator if run and run.last_completed_operator
            else cycle.last_completed_operator
        )
        target = CycleStatus.INITIALIZING
        if job.operator_name == "run_execute":
            target = CycleStatus.RUNNING
        elif job.operator_name in {"run_verify", "failure_postmortem", "verification_report"}:
            target = CycleStatus.VERIFYING
        create_state_snapshot(
            session,
            cycle=cycle,
            target_state=target,
            actor=actor,
            reason=(
                f"Resuming from {resumed_from or 'start'}"
                f" via job {job.public_id}"
            ),
            context={
                "job_public_id": job.public_id,
                "resumed_from": resumed_from,
                "run_public_id": run.public_id if run else None,
            },
        )
    else:
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
        # Record cycle-level progress for auditability.
        cycle.last_completed_operator = job.operator_name
        cycle.last_completed_job_id = job.id
        # Record run-level progress for accurate run resume targeting.
        run = _run_for_job(session, job)
        if run is not None:
            run.last_completed_operator = job.operator_name
            run.last_completed_job_id = job.id
        session.flush()
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


def _run_cycle_independent_job(
    session: Session, config: AppConfig, actor: Actor, job: JobModel,
) -> str:
    """Execute a job that is not tied to any research cycle."""
    operator = OPERATOR_REGISTRY[job.operator_name]
    log.info(
        "operator_starting",
        job_id=job.public_id,
        operator=job.operator_name,
        cycle_independent=True,
    )
    try:
        operator(session, config, actor, None, job)
        mark_job_succeeded(session, job)
        log.info("operator_succeeded", job_id=job.public_id, operator=job.operator_name)
        return "job_succeeded"
    except Exception as exc:
        log.error(
            "operator_failed",
            job_id=job.public_id,
            operator=job.operator_name,
            error=str(exc),
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
