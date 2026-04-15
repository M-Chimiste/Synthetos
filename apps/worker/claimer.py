"""Job claim logic wrapper used by the main worker loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from libs.core.logging import get_logger
from libs.core.services.job_service import claim_job

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from libs.storage.models.jobs import Job

log = get_logger("worker.claimer")


def try_claim(session_factory: sessionmaker[Session], worker_id: str) -> Job | None:
    """Attempt to claim the next pending job.

    Opens a session, calls claim_job, and returns the Job if one was
    claimed.  Returns None when the queue is empty.
    """
    with session_factory() as session:
        job = claim_job(session, worker_id)
        if job is not None:
            log.info(
                "job_claimed",
                job_id=str(job.id),
                job_type=job.job_type,
                worker_id=worker_id,
            )
        return job
