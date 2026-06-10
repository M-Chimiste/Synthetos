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
from apps.worker.heartbeat import JobSupervisor
from apps.worker.periodic import run_periodic_tasks
from libs.analysis.operators._common import (
    AnalysisStateError,
    analysis_session_id_from_payload,
    load_analysis_session,
)
from libs.analysis.operators._common import (
    mark_failed as mark_analysis_failed,
)
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.errors import ErrorClass
from libs.core.event_types import JobLifecycleEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger, setup_logging
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.run_context import (
    CancelToken,
    JobContext,
    current_job_context,
)
from libs.core.services.goal_service import enqueue_goal_advance_sync
from libs.core.services.job_service import (
    cancel_job_record,
    complete_job,
    get_job,
    pause_job,
    retry_or_fail_job,
    start_job,
)
from libs.core.state_machine import ALLOWED_TRANSITIONS, validate_transition
from libs.core.types import ActorType, CycleStatus, JobStatus
from libs.discovery.operators._common import (
    DiscoveryStateError,
    load_session,
    mark_failed,
    session_id_from_payload,
)
from libs.execution.operators._common import (
    ExecutionStateError,
    load_run_record,
    run_record_id_from_payload,
)
from libs.ideation.operators._common import (
    IdeationStateError,
    hypothesis_session_id_from_payload,
    load_hypothesis_session,
)
from libs.ideation.operators._common import (
    mark_failed as mark_ideation_failed,
)
from libs.storage.base import get_sync_session_factory
from libs.storage.models.research import ResearchCycle

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

    from sqlalchemy.orm import Session

    from libs.storage.models.jobs import Job

_DEFAULT_POLL_INTERVAL = 1.0

log = get_logger("worker")

_GOAL_ADVANCE_SUCCESS_JOBS = {
    "discovery_finalize",
    "analysis_evidence",
    "hypothesis_rank",
    "protocol_compile",
}

_GOAL_ADVANCE_FAILURE_PREFIXES = (
    "discovery_",
    "analysis_",
    "hypothesis_",
    "protocol_",
)


def _resolve_charter_id(session_factory, job: Job) -> UUID | None:
    """Resolve the charter ID for a job by looking up its cycle."""
    if job.cycle_id is None:
        return None

    with session_factory() as session:
        cycle = session.get(ResearchCycle, job.cycle_id)
        if cycle is None:
            return None
        return cycle.charter_id


def _goal_id_for_job(session: Session, job: Job) -> str | None:
    if job.cycle_id is None:
        return None
    cycle = session.get(ResearchCycle, job.cycle_id)
    if cycle is None:
        return None
    goal_cfg = (cycle.config or {}).get("goal") or {}
    goal_id = goal_cfg.get("goal_id")
    return str(goal_id) if goal_id else None


def _enqueue_goal_advance_after_success(session: Session, job: Job) -> None:
    if job.cycle_id is None or job.job_type not in _GOAL_ADVANCE_SUCCESS_JOBS:
        return
    goal_id = _goal_id_for_job(session, job)
    if not goal_id:
        return
    enqueue_goal_advance_sync(
        session,
        cycle_id=job.cycle_id,
        goal_id=goal_id,
        trigger=f"{job.job_type}_completed",
    )


def _enqueue_goal_advance_after_failure(
    session: Session,
    *,
    job: Job,
    error: str,
    discovery_session_id: UUID | None = None,
    analysis_session_id: UUID | None = None,
    analysis_paper_card_id: UUID | None = None,
    ideation_session_id: UUID | None = None,
) -> None:
    if job.cycle_id is None or not job.job_type.startswith(_GOAL_ADVANCE_FAILURE_PREFIXES):
        return
    if job.job_type.startswith(("execution_", "verification_")):
        return
    goal_id = _goal_id_for_job(session, job)
    if not goal_id:
        return
    session_id = discovery_session_id or analysis_session_id or ideation_session_id
    enqueue_goal_advance_sync(
        session,
        cycle_id=job.cycle_id,
        goal_id=goal_id,
        trigger=f"{job.job_type}_failed",
        failure={
            "failed_job_id": str(job.id),
            "job_type": job.job_type,
            "job_payload": job.payload or {},
            "session_id": str(session_id) if session_id else None,
            "paper_card_id": str(analysis_paper_card_id) if analysis_paper_card_id else None,
            "error": error,
        },
    )


def _should_enqueue_goal_advance_after_failure(job: Job) -> bool:
    if job.cycle_id is None:
        return False
    if not job.job_type.startswith(_GOAL_ADVANCE_FAILURE_PREFIXES):
        return False
    return not job.job_type.startswith(("execution_", "verification_"))


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
    if current_status == CycleStatus.closed and target_status != CycleStatus.closed:
        log.info(
            "state_patch_ignored_cycle_closed",
            cycle_id=str(cycle.id),
            target_status=target_status.value,
            worker_id=worker_id,
        )
        return
    transition_path = _state_transition_path(current_status, target_status)
    previous_status = current_status
    for next_status in transition_path:
        validate_transition(previous_status, next_status)
        cycle.status = next_status
        cycle.updated_at = utcnow()

        if next_status == CycleStatus.discovery_ready and cycle.started_at is None:
            cycle.started_at = cycle.updated_at
        if next_status == CycleStatus.closed:
            cycle.completed_at = cycle.updated_at

        emit_event_sync(
            session,
            event_type="research_cycle_transitioned",
            charter_id=charter_id or cycle.charter_id,
            cycle_id=cycle.id,
            payload={
                "from_status": previous_status.value,
                "to_status": next_status.value,
            },
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )
        previous_status = next_status


def _state_transition_path(
    current_status: CycleStatus,
    target_status: CycleStatus,
) -> list[CycleStatus]:
    if current_status == target_status:
        return []
    if target_status in ALLOWED_TRANSITIONS.get(current_status, []):
        return [target_status]

    queue: list[tuple[CycleStatus, list[CycleStatus]]] = [(current_status, [])]
    visited = {current_status}
    while queue:
        status, path = queue.pop(0)
        for next_status in ALLOWED_TRANSITIONS.get(status, []):
            if next_status in visited:
                continue
            next_path = [*path, next_status]
            if next_status == target_status:
                return next_path
            visited.add(next_status)
            queue.append((next_status, next_path))

    validate_transition(current_status, target_status)
    return [target_status]


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


def _mark_discovery_job_failed(
    session: Session,
    *,
    job: Job,
    error: str,
) -> tuple[UUID | None, bool]:
    """Mark the linked discovery session failed for a failed discovery job."""
    if not job.job_type.startswith("discovery_"):
        return None, False

    try:
        session_id = session_id_from_payload(
            OperatorInput(
                cycle_id=job.cycle_id or UUID(int=0),
                charter_id=UUID(int=0),
                job_id=job.id,
                job_type=job.job_type,
                payload=job.payload or {},
            )
        )
        discovery = load_session(session, session_id)
    except (DiscoveryStateError, ValueError):
        return None, False

    changed = mark_failed(
        discovery,
        step=job.job_type.removeprefix("discovery_"),
        error=error,
        detail={
            "job_id": str(job.id),
            "job_type": job.job_type,
        },
    )
    return session_id, changed


def _mark_analysis_job_failed(
    session: Session,
    *,
    job: Job,
    error: str,
) -> tuple[UUID | None, UUID | None, bool]:
    """Mark the linked analysis session failed for a failed analysis job."""
    if not job.job_type.startswith("analysis_"):
        return None, None, False

    try:
        session_id = analysis_session_id_from_payload(
            OperatorInput(
                cycle_id=job.cycle_id or UUID(int=0),
                charter_id=UUID(int=0),
                job_id=job.id,
                job_type=job.job_type,
                payload=job.payload or {},
            )
        )
        analysis = load_analysis_session(session, session_id)
    except (AnalysisStateError, ValueError):
        return None, None, False

    changed = mark_analysis_failed(
        analysis,
        step=job.job_type.removeprefix("analysis_"),
        error=error,
        detail={
            "job_id": str(job.id),
            "job_type": job.job_type,
        },
    )
    return session_id, analysis.paper_card_id, changed


def _mark_ideation_job_failed(
    session: Session,
    *,
    job: Job,
    error: str,
) -> tuple[UUID | None, bool]:
    """Mark the linked hypothesis session failed for a failed ideation job."""
    if not job.job_type.startswith("hypothesis_"):
        return None, False

    try:
        session_id = hypothesis_session_id_from_payload(
            OperatorInput(
                cycle_id=job.cycle_id or UUID(int=0),
                charter_id=UUID(int=0),
                job_id=job.id,
                job_type=job.job_type,
                payload=job.payload or {},
            )
        )
        hs = load_hypothesis_session(session, session_id)
    except (IdeationStateError, ValueError):
        return None, False

    changed = mark_ideation_failed(
        hs,
        step=job.job_type.removeprefix("hypothesis_"),
        error=error,
        detail={"job_id": str(job.id), "job_type": job.job_type},
    )
    return session_id, changed


def _mark_execution_job_failed(
    session: Session,
    *,
    job: Job,
    error: str,
) -> tuple[UUID | None, bool]:
    """Mark the linked run record failed for a failed execution/verification job."""
    prefixes = ("execution_", "verification_", "protocol_")
    if not any(job.job_type.startswith(p) for p in prefixes):
        return None, False

    try:
        run_id = run_record_id_from_payload(
            OperatorInput(
                cycle_id=job.cycle_id or UUID(int=0),
                charter_id=UUID(int=0),
                job_id=job.id,
                job_type=job.job_type,
                payload=job.payload or {},
            )
        )
        run_record = load_run_record(session, run_id)
    except (ExecutionStateError, ValueError):
        return None, False

    if run_record.status in ("failed", "cancelled"):
        return run_id, False

    run_record.status = "failed"
    run_record.error = error
    run_record.completed_at = utcnow()
    return run_id, True


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

    # Startup: reclaim any stale jobs left over from a prior worker crash and
    # seed the periodic-tick timer.
    startup_counts = run_periodic_tasks(session_factory, settings=settings)
    log.info("worker_startup_periodic", **startup_counts)
    last_periodic = time.monotonic()

    try:
        while not shutdown_requested:
            now_mono = time.monotonic()
            if now_mono - last_periodic >= settings.worker_periodic_tick_s:
                counts = run_periodic_tasks(session_factory, settings=settings)
                if counts.get("reclaimed") or counts.get("failed_exhausted"):
                    log.info("worker_periodic_tick", **counts)
                last_periodic = now_mono

            job = try_claim(session_factory, worker_id)
            if job is None:
                time.sleep(poll_interval)
                continue

            with session_factory() as session:
                job = start_job(session, job.id)
                charter_id = _resolve_charter_id(session_factory, job)
                attempt_number = int(job.attempt_count or 0) + 1
                emit_event_sync(
                    session,
                    event_type="job_started",
                    charter_id=charter_id,
                    cycle_id=job.cycle_id,
                    payload={"job_id": str(job.id), "job_type": job.job_type},
                    actor_type=ActorType.worker,
                    actor_id=worker_id,
                )
                emit_event_sync(
                    session,
                    event_type=JobLifecycleEvents.attempt_started.value,
                    charter_id=charter_id,
                    cycle_id=job.cycle_id,
                    payload={
                        "job_id": str(job.id),
                        "job_type": job.job_type,
                        "attempt": attempt_number,
                        "max_attempts": int(job.max_attempts or 1),
                    },
                    actor_type=ActorType.worker,
                    actor_id=worker_id,
                )
                session.commit()

            # Supervise the claimed job: heartbeat + cancel polling + deadline.
            cancel_token = CancelToken()
            supervisor = JobSupervisor(
                session_factory,
                job.id,
                token=cancel_token,
                deadline_s=float(
                    settings.job_timeout_overrides.get(job.job_type, settings.job_default_timeout_s)
                ),
                started_at=job.started_at,
                grace_s=float(settings.job_cancel_grace_s),
            )
            supervisor.start()
            ctx_token = current_job_context.set(
                JobContext(job_id=job.id, cycle_id=job.cycle_id, cancel_token=cancel_token)
            )

            try:
                op_input = _build_operator_input(session_factory, job)
                log.info(
                    "job_executing",
                    job_id=str(job.id),
                    job_type=job.job_type,
                    attempt=attempt_number,
                    worker_id=worker_id,
                )
                result = execute(op_input)
            finally:
                current_job_context.reset(ctx_token)
                supervisor.stop()

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
                    try:
                        _enqueue_goal_advance_after_success(session, current_job)
                    except Exception:
                        # Never let goal bookkeeping roll back complete_job: a
                        # rollback here leaves the job "running" with a dead
                        # heartbeat -> reclaim -> full re-execution.
                        log.exception(
                            "goal_advance_enqueue_failed",
                            job_id=str(current_job.id),
                            trigger="success",
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
                    _handle_failure(
                        session,
                        job=current_job,
                        result=result,
                        charter_id=charter_id,
                        worker_id=worker_id,
                    )
    finally:
        log.info("worker_stopped", worker_id=worker_id)


def _failure_error_detail(result: OperatorResult, attempt: int) -> dict[str, Any]:
    failure = result.failure
    detail: dict[str, Any] = {
        "error_class": (failure.error_class.value if failure else ErrorClass.permanent.value),
        "attempt": attempt,
        "occurred_at": utcnow().isoformat(),
    }
    if failure is not None:
        detail["exc_type"] = failure.exc_type
        detail["traceback"] = failure.traceback
    return detail


def _emit_attempt_failed(
    session: Session,
    *,
    job: Job,
    error: str,
    error_class: ErrorClass,
    attempt: int,
    charter_id: UUID | None,
    worker_id: str,
) -> None:
    emit_event_sync(
        session,
        event_type=JobLifecycleEvents.attempt_failed.value,
        charter_id=charter_id,
        cycle_id=job.cycle_id,
        payload={
            "job_id": str(job.id),
            "job_type": job.job_type,
            "attempt": attempt,
            "error_class": error_class.value,
            "error": error[:500],
        },
        actor_type=ActorType.worker,
        actor_id=worker_id,
    )


def _handle_failure(
    session: Session,
    *,
    job: Job,
    result: OperatorResult,
    charter_id: UUID | None,
    worker_id: str,
) -> None:
    """Route a failed operator result: cancelled, retry-scheduled, or final.

    Phase/session failure side-effects (marking discovery/analysis/ideation
    sessions failed, goal-advance) run only on FINAL failure -- a scheduled
    retry must not poison downstream state, and a user cancel is not a
    failure at all.
    """
    error = result.error or "unknown error"
    failure = result.failure
    error_class = failure.error_class if failure else ErrorClass.permanent
    attempt = int(job.attempt_count or 0) + 1
    error_detail = _failure_error_detail(result, attempt)

    _persist_operator_events(
        session,
        charter_id=charter_id,
        cycle_id=job.cycle_id,
        events=result.events,
        worker_id=worker_id,
    )

    # User cancel honored mid-run: mark cancelled, skip all failure side-effects.
    if error_class == ErrorClass.cancelled:
        cancel_job_record(session, job.id, error_detail=error_detail)
        emit_event_sync(
            session,
            event_type="job_cancelled_acknowledged",
            charter_id=charter_id,
            cycle_id=job.cycle_id,
            payload={"job_id": str(job.id), "job_type": job.job_type},
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )
        session.commit()
        log.info("job_cancelled", job_id=str(job.id), job_type=job.job_type)
        return

    if error_class == ErrorClass.timeout:
        emit_event_sync(
            session,
            event_type=JobLifecycleEvents.timeout_signalled.value,
            charter_id=charter_id,
            cycle_id=job.cycle_id,
            payload={"job_id": str(job.id), "job_type": job.job_type, "attempt": attempt},
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )

    # A job the user paused mid-run keeps its paused status; record the error.
    if job.status == JobStatus.paused:
        job.error = error
        job.error_detail = error_detail
        _emit_attempt_failed(
            session,
            job=job,
            error=error,
            error_class=error_class,
            attempt=attempt,
            charter_id=charter_id,
            worker_id=worker_id,
        )
        session.commit()
        return

    retryable = error_class in (ErrorClass.transient, ErrorClass.timeout)
    updated = retry_or_fail_job(
        session,
        job.id,
        error=error,
        error_detail=error_detail,
        retryable=retryable,
    )
    _emit_attempt_failed(
        session,
        job=job,
        error=error,
        error_class=error_class,
        attempt=attempt,
        charter_id=charter_id,
        worker_id=worker_id,
    )

    if updated.status == JobStatus.pending:
        # Retry scheduled: no failure side-effects, downstream state untouched.
        emit_event_sync(
            session,
            event_type=JobLifecycleEvents.retry_scheduled.value,
            charter_id=charter_id,
            cycle_id=job.cycle_id,
            payload={
                "job_id": str(job.id),
                "job_type": job.job_type,
                "attempt": attempt,
                "max_attempts": int(updated.max_attempts or 1),
                "next_attempt_at": (updated.not_before.isoformat() if updated.not_before else None),
            },
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )
        session.commit()
        log.warning(
            "job_retry_scheduled",
            job_id=str(job.id),
            job_type=job.job_type,
            attempt=attempt,
            error=error,
            worker_id=worker_id,
        )
        return

    # Final failure: mark linked sessions failed and notify the goal system.
    discovery_session_id, discovery_failure_changed = _mark_discovery_job_failed(
        session, job=job, error=error
    )
    (
        analysis_session_id,
        analysis_paper_card_id,
        analysis_failure_changed,
    ) = _mark_analysis_job_failed(session, job=job, error=error)
    ideation_session_id, ideation_failure_changed = _mark_ideation_job_failed(
        session, job=job, error=error
    )
    execution_run_id, execution_failure_changed = _mark_execution_job_failed(
        session, job=job, error=error
    )
    if ideation_failure_changed:
        emit_event_sync(
            session,
            event_type="ideation.session_failed",
            charter_id=charter_id,
            cycle_id=job.cycle_id,
            payload={
                "hypothesis_session_id": str(ideation_session_id),
                "operator": job.job_type,
                "error": error,
            },
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )
    if execution_failure_changed:
        emit_event_sync(
            session,
            event_type="execution.run_failed",
            charter_id=charter_id,
            cycle_id=job.cycle_id,
            payload={
                "run_record_id": str(execution_run_id),
                "operator": job.job_type,
                "error": error,
            },
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )
    if discovery_failure_changed:
        emit_event_sync(
            session,
            event_type="discovery.session_failed",
            charter_id=charter_id,
            cycle_id=job.cycle_id,
            payload={
                "session_id": str(discovery_session_id),
                "operator": job.job_type,
                "error": error,
            },
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )
    if analysis_failure_changed:
        emit_event_sync(
            session,
            event_type="analysis.session_failed",
            charter_id=charter_id,
            cycle_id=job.cycle_id,
            payload={
                "analysis_session_id": str(analysis_session_id),
                "paper_card_id": str(analysis_paper_card_id),
                "operator": job.job_type,
                "error": error,
            },
            actor_type=ActorType.worker,
            actor_id=worker_id,
        )
    if _should_enqueue_goal_advance_after_failure(job):
        try:
            _enqueue_goal_advance_after_failure(
                session,
                job=job,
                error=error,
                discovery_session_id=discovery_session_id,
                analysis_session_id=analysis_session_id,
                analysis_paper_card_id=analysis_paper_card_id,
                ideation_session_id=ideation_session_id,
            )
        except Exception:
            log.exception(
                "goal_advance_enqueue_failed",
                job_id=str(job.id),
                trigger="failure",
            )
    emit_event_sync(
        session,
        event_type="job_failed",
        charter_id=charter_id,
        cycle_id=job.cycle_id,
        payload={"job_id": str(job.id), "error": error},
        actor_type=ActorType.worker,
        actor_id=worker_id,
    )
    session.commit()
    log.warning(
        "job_failed",
        job_id=str(job.id),
        job_type=job.job_type,
        error=error,
        attempt=attempt,
        worker_id=worker_id,
    )


def main() -> None:
    """CLI entry point."""
    run()


if __name__ == "__main__":
    main()
