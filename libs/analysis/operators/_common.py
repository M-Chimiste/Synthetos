"""Shared helpers for analysis operators."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.clock import utcnow
from libs.core.operators import OperatorInput
from libs.core.services.job_service import create_job
from libs.storage.models.analysis import AnalysisSession


class AnalysisStateError(Exception):
    """Raised when an operator cannot find the state it needs."""


def analysis_session_id_from_payload(op_input: OperatorInput) -> UUID:
    """Extract the analysis session id from a job payload."""
    raw = op_input.payload.get("analysis_session_id")
    if raw is None:
        raise AnalysisStateError(
            f"job {op_input.job_id} payload is missing required 'analysis_session_id'"
        )
    if isinstance(raw, UUID):
        return raw
    return UUID(str(raw))


def load_analysis_session(session: Session, session_id: UUID) -> AnalysisSession:
    """Load an analysis session row or raise."""
    result = session.execute(
        select(AnalysisSession).where(AnalysisSession.id == session_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise AnalysisStateError(f"analysis session {session_id} not found")
    return obj


def append_step_log(
    analysis: AnalysisSession,
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
    log = list(analysis.step_log or [])
    log.append(entry)
    analysis.step_log = log


def merge_stats(analysis: AnalysisSession, more: dict[str, Any]) -> None:
    """Shallow-merge new stats into the session's stats blob."""
    stats = dict(analysis.stats or {})
    stats.update(more)
    analysis.stats = stats


def analysis_budget(analysis: AnalysisSession) -> dict[str, Any]:
    """Return the normalized budget dict for an analysis session."""
    return dict(analysis.budget or {})


def enqueue_next(
    session: Session,
    *,
    cycle_id: UUID,
    next_job_type: str,
    analysis_session_id: UUID,
) -> UUID:
    """Insert the next analysis operator job and return its id."""
    job = create_job(
        session,
        cycle_id=cycle_id,
        job_type=next_job_type,
        payload={"analysis_session_id": str(analysis_session_id)},
        priority=10,
    )
    return job.id


def mark_started_if_needed(analysis: AnalysisSession) -> None:
    if analysis.started_at is None:
        analysis.started_at = utcnow()


def mark_failed(
    analysis: AnalysisSession,
    *,
    step: str,
    error: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Mark an analysis session failed and append a structured step-log entry.

    Returns ``True`` when the failure state changed.
    """
    if analysis.status == "failed" and analysis.error == error:
        return False

    analysis.status = "failed"
    analysis.error = error
    analysis.completed_at = utcnow()

    payload = dict(detail or {})
    payload["error"] = error
    append_step_log(
        analysis,
        step=step,
        status="failed",
        detail=payload,
    )
    return True
