"""Shared helpers for discovery operators."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.clock import utcnow
from libs.core.operators import OperatorInput
from libs.core.services.job_service import create_job
from libs.storage.models.discovery import DiscoverySession, ProblemProfile


class DiscoveryStateError(Exception):
    """Raised when an operator cannot find the state it needs."""


def session_id_from_payload(op_input: OperatorInput) -> UUID:
    """Extract the discovery session id from a job payload."""
    raw = op_input.payload.get("session_id")
    if raw is None:
        raise DiscoveryStateError(f"job {op_input.job_id} payload is missing required 'session_id'")
    if isinstance(raw, UUID):
        return raw
    return UUID(str(raw))


def load_session(session: Session, session_id: UUID) -> DiscoverySession:
    """Load a discovery session row or raise."""
    result = session.execute(select(DiscoverySession).where(DiscoverySession.id == session_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise DiscoveryStateError(f"discovery session {session_id} not found")
    return obj


def load_profile(session: Session, profile_id: UUID) -> ProblemProfile:
    result = session.execute(select(ProblemProfile).where(ProblemProfile.id == profile_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise DiscoveryStateError(f"problem profile {profile_id} not found")
    return obj


def append_step_log(
    discovery: DiscoverySession,
    *,
    step: str,
    status: str = "ok",
    detail: dict[str, Any] | None = None,
) -> None:
    """Append a step entry to the session's structured step log."""
    entry: dict[str, Any] = {
        "step": step,
        "status": status,
        "at": utcnow().isoformat(),
    }
    if detail:
        entry["detail"] = detail
    log = list(discovery.step_log or [])
    log.append(entry)
    discovery.step_log = log


def merge_stats(discovery: DiscoverySession, more: dict[str, Any]) -> None:
    """Shallow-merge new stats into the session's stats blob."""
    stats = dict(discovery.stats or {})
    stats.update(more)
    discovery.stats = stats


def enqueue_next(
    session: Session,
    *,
    cycle_id: UUID,
    next_job_type: str,
    session_id: UUID,
) -> UUID:
    """Insert the next discovery operator job and return its id."""
    job = create_job(
        session,
        cycle_id=cycle_id,
        job_type=next_job_type,
        payload={"session_id": str(session_id)},
        priority=10,  # discovery jobs jump the queue ahead of plain echo jobs
    )
    return job.id


def mark_started_if_needed(discovery: DiscoverySession) -> None:
    if discovery.started_at is None:
        discovery.started_at = utcnow()


def mark_failed(
    discovery: DiscoverySession,
    *,
    step: str,
    error: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Mark a discovery session failed and append a structured step-log entry.

    Returns ``True`` when the failure state changed, ``False`` when the session
    already carried the same failure.
    """
    if discovery.status == "failed" and discovery.error == error:
        return False

    discovery.status = "failed"
    discovery.error = error
    discovery.completed_at = utcnow()

    payload = dict(detail or {})
    payload["error"] = error
    append_step_log(
        discovery,
        step=step,
        status="failed",
        detail=payload,
    )
    return True
