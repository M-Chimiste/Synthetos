"""Persistence for LLM call transcripts (reliability-layer telemetry).

Writes use a dedicated short-lived sync session committed immediately --
never the worker's result transaction. Transcripts must survive operator
failure (the calls you most need to debug are the ones whose job died), and
immediate commits give live visibility into a multi-call operator while it
runs. A recording failure is swallowed and logged: telemetry must never fail
the LLM call it describes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.logging import get_logger
from libs.core.run_context import get_job_context
from libs.storage.base import get_sync_session_factory
from libs.storage.models.llm_calls import LLMCall

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from libs.adapters.llm.reliability import LLMCallRecord

log = get_logger(__name__)


def _messages_hash(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def record_llm_call_sync(record: LLMCallRecord) -> None:
    """Persist one LLM call record in its own committed session.

    Job/cycle identity comes from the worker's job context var (None for
    API-process calls). Prompt and response text are stored only when
    ``LAB_LLM_LOG_PROMPTS`` is enabled; the messages hash is always stored.
    """
    settings = get_settings()
    if not settings.llm_call_logging_enabled:
        return

    ctx = get_job_context()
    log_prompts = settings.llm_log_prompts
    response_text = record.response_text
    if response_text is not None:
        if not log_prompts:
            response_text = None
        elif len(response_text) > settings.llm_log_max_response_chars:
            response_text = response_text[: settings.llm_log_max_response_chars]

    try:
        factory = get_sync_session_factory()
        with factory() as session:
            session.add(
                LLMCall(
                    id=uuid7(),
                    job_id=ctx.job_id if ctx else None,
                    cycle_id=ctx.cycle_id if ctx else None,
                    role=record.role,
                    provider=record.provider,
                    model=record.model,
                    base_url=record.base_url,
                    request_kind=record.request_kind,
                    response_model=record.response_model,
                    messages_hash=_messages_hash(record.messages),
                    messages=record.messages if log_prompts else None,
                    response_text=response_text,
                    finish_reason=record.finish_reason,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    latency_ms=record.latency_ms,
                    attempts=record.attempts,
                    outcome=record.outcome,
                    fallback_used=record.fallback_used,
                    error=record.error,
                    attempt_log=record.attempt_log or None,
                    created_at=utcnow(),
                )
            )
            session.commit()
    except Exception:
        log.exception("llm_call_record_failed", role=record.role, outcome=record.outcome)


async def record_llm_call(record: LLMCallRecord) -> None:
    """Async wrapper: the ~ms write must not block concurrent LLM tasks."""
    await asyncio.to_thread(record_llm_call_sync, record)


def role_success_rates(
    session: Session,
    *,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Aggregate per-role call outcomes: totals, success rate, latency, attempts."""
    query = select(
        LLMCall.role,
        func.count().label("total"),
        func.count().filter(LLMCall.outcome == "success").label("successes"),
        func.avg(LLMCall.latency_ms).label("avg_latency_ms"),
        func.avg(LLMCall.attempts).label("avg_attempts"),
        func.count().filter(LLMCall.fallback_used).label("fallback_calls"),
    ).group_by(LLMCall.role)
    if since is not None:
        query = query.where(LLMCall.created_at >= since)

    rows = session.execute(query).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        total = int(row.total or 0)
        successes = int(row.successes or 0)
        out.append(
            {
                "role": row.role,
                "total": total,
                "successes": successes,
                "success_rate": (successes / total) if total else 0.0,
                "avg_latency_ms": float(row.avg_latency_ms) if row.avg_latency_ms else None,
                "avg_attempts": float(row.avg_attempts) if row.avg_attempts else None,
                "fallback_calls": int(row.fallback_calls or 0),
            }
        )
    return sorted(out, key=lambda r: r["role"])
