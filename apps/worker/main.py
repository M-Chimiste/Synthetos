"""Synthetos worker entry point.

Polls the job queue, claims work, dispatches to operators, and reports
results.  All database access is synchronous.

Usage::

    uv run python -m apps.worker
"""

from __future__ import annotations

import signal
import time
from typing import TYPE_CHECKING
from uuid import UUID

from uuid_utils import uuid7

from apps.worker.claimer import try_claim
from apps.worker.executor import execute
from apps.worker.heartbeat import HeartbeatThread
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger, setup_logging
from libs.core.operators import OperatorInput
from libs.core.services.job_service import (
    complete_job,
    fail_job,
    get_job,
    pause_job,
    start_job,
)
from libs.core.state_machine import validate_transition
from libs.core.types import ActorType, CycleStatus, JobStatus
from libs.storage.base import get_sync_session_factory
from libs.storage.models.research import ResearchCycle

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

    from sqlalchemy.orm import Session

    from libs.storage.models.jobs import Job

_DEFAULT_POLL_INTERVAL = 1.0

log = get_logger("worker")


def _resolve_charter_id(session_factory, job: Job) -> UUID | None:
    """Resolve the charter ID for a job by looking up its cycle."""
    if job.cycle_id is None:
        return None

    with session_factory() as session:
        cycle = session.get(ResearchCycle, job.cycle_id)
        if cycle is None:
            return None
        return cycle.charter_id


def _build_operator_input(session_factory, job: Job) -> OperatorInput:
    """Construct an OperatorInput from a claimed Job row."""
    # cycle_id and charter_id may be None for system-level jobs.
    cycle_id = job.cycle_id or UUID(int=0)
    charter_id = _resolve_charter_id(session_factory, job) or UUID(int=0)
    return OperatorInput(
        cycle_id=cycle_id,
        charter_id=charter_id,
        job_id=job.id,
        job_type=job.job_type,
        payload=job.payload or {},
    )


def _apply_state_patch(
    session: Session,
    *,
    cycle_id: UUID | None,
    charter_id: UUID | None,
    state_patch: dict[str, Any],
    worker_id: str,
) -> None:
    """Apply the minimal Phase 0 durable state effects from an operator result."""
    if cycle_id is None:
        return

    raw_target = state_patch.get("cycle_status") or state_patch.get("target_status")
    if raw_target is None:
        return

    cycle = session.get(ResearchCycle, cycle_id)
    if cycle is None:
        return

    target_status = CycleStatus(raw_target)
    current_status = CycleStatus(cycle.status)
    validate_transition(current_status, target_status)
    cycle.status = target_status
    cycle.updated_at = utcnow()

    if target_status == CycleStatus.discovery_ready and cycle.started_at is None:
        cycle.started_at = cycle.updated_at
    if target_status == CycleStatus.closed:
        cycle.completed_at = cycle.updated_at

    emit_event_sync(
        session,
        event_type="research_cycle_transitioned",
        charter_id=charter_id or cycle.charter_id,
        cycle_id=cycle.id,
        payload={
            "from_status": current_status.value,
            "to_status": target_status.value,
        },
        actor_type=ActorType.worker,
        actor_id=worker_id,
    )


def _persist_operator_events(
    session: Session,
    *,
    charter_id: UUID | None,
    cycle_id: UUID | None,
    events: Iterable[dict[str, Any]],
    worker_id: str,
) -> None:
    """Persist operator-emitted events into the domain event log."""
    for event in events:
        emit_event_sync(
            session,
            event_type=event["event_type"],
            charter_id=charter_id,
            cycle_id=cycle_id,
            payload=event.get("payload"),
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )


def run(*, poll_interval: float = _DEFAULT_POLL_INTERVAL) -> None:
    """Main worker loop."""
    setup_logging()
    settings = get_settings()
    worker_id = f"worker-{uuid7()}"
    session_factory = get_sync_session_factory(settings.sync_db_url)

    log.info("worker_started", worker_id=worker_id)

    shutdown_requested = False

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal shutdown_requested
        sig_name = signal.Signals(signum).name
        log.info("shutdown_signal_received", signal=sig_name, worker_id=worker_id)
        shutdown_requested = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        while not shutdown_requested:
            job = try_claim(session_factory, worker_id)
            if job is None:
                time.sleep(poll_interval)
                continue

            with session_factory() as session:
                job = start_job(session, job.id)
                charter_id = _resolve_charter_id(session_factory, job)
                emit_event_sync(
                    session,
                    event_type="job_started",
                    charter_id=charter_id,
                    cycle_id=job.cycle_id,
                    payload={"job_id": str(job.id), "job_type": job.job_type},
                    actor_type=ActorType.worker,
                    actor_id=worker_id,
                )
                session.commit()

            # Start heartbeat for the claimed job
            heartbeat = HeartbeatThread(session_factory, job.id)
            heartbeat.start()

            try:
                op_input = _build_operator_input(session_factory, job)
                log.info(
                    "job_executing",
                    job_id=str(job.id),
                    job_type=job.job_type,
                    worker_id=worker_id,
                )
                result = execute(op_input)
            finally:
                heartbeat.stop()

            # Persist outcome
            with session_factory() as session:
                current_job = get_job(session, job.id)
                if current_job is None:
                    continue

                charter_id = _resolve_charter_id(session_factory, current_job)
                if current_job.status == JobStatus.cancelled:
                    emit_event_sync(
                        session,
                        event_type="job_cancelled_acknowledged",
                        charter_id=charter_id,
                        cycle_id=current_job.cycle_id,
                        payload={"job_id": str(current_job.id)},
                        actor_type=ActorType.worker,
                        actor_id=worker_id,
                    )
                    session.commit()
                    continue

                if result.success:
                    _persist_operator_events(
                        session,
                        charter_id=charter_id,
                        cycle_id=current_job.cycle_id,
                        events=result.events,
                        worker_id=worker_id,
                    )
                    _apply_state_patch(
                        session,
                        cycle_id=current_job.cycle_id,
                        charter_id=charter_id,
                        state_patch=result.state_patch,
                        worker_id=worker_id,
                    )

                    if current_job.status == JobStatus.paused:
                        pause_job(
                            session,
                            current_job.id,
                            result={
                                "summary": result.summary,
                                "state_patch": result.state_patch,
                                "artifacts": result.artifacts,
                                "events": result.events,
                            },
                        )
                        emit_event_sync(
                            session,
                            event_type="job_paused_at_checkpoint",
                            charter_id=charter_id,
                            cycle_id=current_job.cycle_id,
                            payload={"job_id": str(current_job.id)},
                            actor_type=ActorType.worker,
                            actor_id=worker_id,
                        )
                        session.commit()
                        continue

                    complete_job(
                        session,
                        current_job.id,
                        result={
                            "summary": result.summary,
                            "state_patch": result.state_patch,
                            "artifacts": result.artifacts,
                            "events": result.events,
                        },
                    )
                    emit_event_sync(
                        session,
                        event_type="job_completed",
                        charter_id=charter_id,
                        cycle_id=current_job.cycle_id,
                        payload={"job_id": str(current_job.id), "summary": result.summary},
                        actor_type=ActorType.worker,
                        actor_id=worker_id,
                    )
                    session.commit()
                    log.info(
                        "job_completed",
                        job_id=str(current_job.id),
                        job_type=current_job.job_type,
                        summary=result.summary,
                        worker_id=worker_id,
                    )
                else:
                    fail_job(session, current_job.id, result.error or "unknown error")
                    emit_event_sync(
                        session,
                        event_type="job_failed",
                        charter_id=charter_id,
                        cycle_id=current_job.cycle_id,
                        payload={"job_id": str(current_job.id), "error": result.error},
                        actor_type=ActorType.worker,
                        actor_id=worker_id,
                    )
                    session.commit()
                    log.warning(
                        "job_failed",
                        job_id=str(current_job.id),
                        job_type=current_job.job_type,
                        error=result.error,
                        worker_id=worker_id,
                    )
    finally:
        log.info("worker_stopped", worker_id=worker_id)


def main() -> None:
    """CLI entry point."""
    run()


if __name__ == "__main__":
    main()
