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
from libs.core.config import get_settings
from libs.core.logging import get_logger, setup_logging
from libs.core.operators import OperatorInput
from libs.core.services.job_service import complete_job, fail_job
from libs.storage.base import get_sync_session_factory

if TYPE_CHECKING:
    from libs.storage.models.jobs import Job

_DEFAULT_POLL_INTERVAL = 1.0

log = get_logger("worker")


def _build_operator_input(job: Job) -> OperatorInput:
    """Construct an OperatorInput from a claimed Job row."""
    # cycle_id and charter_id may be None for system-level jobs.
    cycle_id = job.cycle_id or UUID(int=0)
    charter_id = UUID(int=0)  # resolved later when cycle lookup is needed
    return OperatorInput(
        cycle_id=cycle_id,
        charter_id=charter_id,
        job_id=job.id,
        job_type=job.job_type,
        payload=job.payload or {},
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

            # Start heartbeat for the claimed job
            heartbeat = HeartbeatThread(session_factory, job.id)
            heartbeat.start()

            try:
                op_input = _build_operator_input(job)
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
                if result.success:
                    complete_job(
                        session,
                        job.id,
                        result={
                            "summary": result.summary,
                            "state_patch": result.state_patch,
                            "artifacts": result.artifacts,
                            "events": result.events,
                        },
                    )
                    log.info(
                        "job_completed",
                        job_id=str(job.id),
                        job_type=job.job_type,
                        summary=result.summary,
                        worker_id=worker_id,
                    )
                else:
                    fail_job(session, job.id, result.error or "unknown error")
                    log.warning(
                        "job_failed",
                        job_id=str(job.id),
                        job_type=job.job_type,
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
