"""Background heartbeat thread for the currently running job."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from libs.core.logging import get_logger
from libs.core.services.job_service import heartbeat_job

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session, sessionmaker

log = get_logger("worker.heartbeat")

_DEFAULT_INTERVAL_SECONDS = 5.0


class HeartbeatThread:
    """Periodically updates heartbeat_at for the active job.

    Usage::

        hb = HeartbeatThread(session_factory, job_id)
        hb.start()
        # ... do work ...
        hb.stop()
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        job_id: UUID,
        *,
        interval: float = _DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._job_id = job_id
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the heartbeat background thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{self._job_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the heartbeat thread to stop and wait for it to finish."""
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
                    heartbeat_job(session, self._job_id)
            except Exception:
                log.exception(
                    "heartbeat_failed",
                    job_id=str(self._job_id),
                )
