"""Shared helpers for hypothesis pipeline operators."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.clock import utcnow
from libs.core.operators import OperatorInput
from libs.core.services.job_service import create_job
from libs.storage.models.experiment import HypothesisSession


class IdeationStateError(Exception):
    """Raised when an operator cannot find the state it needs."""


def hypothesis_session_id_from_payload(op_input: OperatorInput) -> UUID:
    """Extract the hypothesis session id from a job payload."""
    raw = op_input.payload.get("hypothesis_session_id")
    if raw is None:
        raise IdeationStateError(
            f"job {op_input.job_id} payload is missing required 'hypothesis_session_id'"
        )
    if isinstance(raw, UUID):
        return raw
    return UUID(str(raw))


def load_hypothesis_session(session: Session, session_id: UUID) -> HypothesisSession:
    """Load a hypothesis session row or raise."""
    result = session.execute(
        select(HypothesisSession).where(HypothesisSession.id == session_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise IdeationStateError(f"hypothesis session {session_id} not found")
    return obj


def append_step_log(
    hs: HypothesisSession,
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
    log = list(hs.step_log or [])
    log.append(entry)
    hs.step_log = log


def merge_stats(hs: HypothesisSession, more: dict[str, Any]) -> None:
    """Shallow-merge new stats into the session's stats blob."""
    stats = dict(hs.stats or {})
    stats.update(more)
    hs.stats = stats


def enqueue_next(
    session: Session,
    *,
    cycle_id: UUID,
    next_job_type: str,
    hypothesis_session_id: UUID,
) -> UUID:
    """Insert the next hypothesis operator job and return its id."""
    job = create_job(
        session,
        cycle_id=cycle_id,
        job_type=next_job_type,
        payload={"hypothesis_session_id": str(hypothesis_session_id)},
        priority=10,
    )
    return job.id


def mark_started_if_needed(hs: HypothesisSession) -> None:
    if hs.started_at is None:
        hs.started_at = utcnow()


def mark_failed(
    hs: HypothesisSession,
    *,
    step: str,
    error: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Mark a hypothesis session failed and append a structured step-log entry.

    Returns ``True`` when the failure state changed, ``False`` when the session
    already carried the same failure.
    """
    if hs.status == "failed" and hs.error == error:
        return False

    hs.status = "failed"
    hs.error = error
    hs.completed_at = utcnow()

    payload = dict(detail or {})
    payload["error"] = error
    append_step_log(hs, step=step, status="failed", detail=payload)
    return True
