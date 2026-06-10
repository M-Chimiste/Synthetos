"""Per-job supervisor thread: heartbeat, cancel polling, deadline watchdog.

Each 5-second tick the supervisor:
1. updates ``heartbeat_at`` (liveness for the stale-job reclaimer),
2. observes ``cancel_requested`` (or a legacy direct ``cancelled`` status) in
   the same DB round-trip and trips the job's cancel token,
3. checks the wall-clock deadline and trips the token with reason=timeout,
4. logs loudly if a tripped token hasn't been honored within the grace window.

The supervisor keeps heartbeating after the token trips: reclaiming a job
that is still executing in this process would guarantee double execution.
It never emits domain events (that would race the worker's outcome
transaction); it only updates the heartbeat, sets the token, and logs.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from libs.core.clock import utcnow
from libs.core.logging import get_logger
from libs.core.run_context import CancelReason, CancelToken
from libs.core.services.job_service import heartbeat_job
from libs.core.types import JobStatus

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.orm import Session, sessionmaker

log = get_logger("worker.heartbeat")

_DEFAULT_INTERVAL_SECONDS = 5.0


class JobSupervisor:
    """Heartbeats the active job and supervises cancellation/deadline.

    Usage::

        supervisor = JobSupervisor(
            session_factory, job_id, token=token, deadline_s=14400
        )
        supervisor.start()
        # ... do work ...
        supervisor.stop()
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        job_id: UUID,
        *,
        token: CancelToken | None = None,
        deadline_s: float | None = None,
        started_at: datetime | None = None,
        grace_s: float = 600.0,
        interval: float = _DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._job_id = job_id
        self._token = token
        self._deadline_s = deadline_s
        self._started_at = started_at or utcnow()
        self._grace_s = grace_s
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the supervisor background thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"job-supervisor-{self._job_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the supervisor thread to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval * 2)
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._interval)
            if self._stop_event.is_set():
                break
            try:
                with self._session_factory() as session:
                    status, cancel_requested = heartbeat_job(session, self._job_id)
            except Exception:
                log.exception("heartbeat_failed", job_id=str(self._job_id))
                continue

            self._check_cancel(status, cancel_requested)
            self._check_deadline()
            self._check_grace()

    def _check_cancel(self, status: str | None, cancel_requested: bool) -> None:
        if self._token is None or self._token.cancelled:
            return
        if cancel_requested or status == JobStatus.cancelled.value:
            log.info("job_cancel_observed", job_id=str(self._job_id))
            self._token.cancel(CancelReason.user_cancel)

    def _check_deadline(self) -> None:
        if self._token is None or self._token.cancelled or self._deadline_s is None:
            return
        elapsed = (utcnow() - self._started_at).total_seconds()
        if elapsed > self._deadline_s:
            log.warning(
                "job_timeout_signalled",
                job_id=str(self._job_id),
                deadline_s=self._deadline_s,
                elapsed_s=int(elapsed),
            )
            self._token.cancel(CancelReason.timeout)

    def _check_grace(self) -> None:
        if self._token is None or not self._token.cancelled:
            return
        requested_at = self._token.requested_at
        if requested_at is None:
            return
        overdue = (utcnow() - requested_at).total_seconds()
        if overdue > self._grace_s:
            log.error(
                "job_cancel_not_honored",
                job_id=str(self._job_id),
                reason=self._token.reason.value if self._token.reason else None,
                overdue_s=int(overdue),
            )


# Backwards-compatible alias: existing callers/tests constructed HeartbeatThread.
HeartbeatThread = JobSupervisor
