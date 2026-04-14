"""decay_patterns operator -- decays staleness scores and demotes trust tiers.

Runs periodically (worker enqueue) and on demand (CLI/API). Idempotent:
repeated runs at the same timestamp produce no additional transitions.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from libs.core.clock import utcnow
from libs.core.event_types import PatternEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.patterns.decay import evaluate
from libs.storage.base import get_sync_session_factory
from libs.storage.models.patterns import CanonicalPattern, PeriodicJobState

log = get_logger("patterns.decay")

DEFAULT_MAX_STALENESS_DAYS = 90
JOB_KIND = "decay_patterns"


def _read_max_staleness(payload: dict[str, Any] | None) -> int:
    if not payload:
        return DEFAULT_MAX_STALENESS_DAYS
    raw = payload.get("max_staleness_days")
    if raw is None:
        return DEFAULT_MAX_STALENESS_DAYS
    return int(raw)


def decay_patterns_operator(op_input: OperatorInput) -> OperatorResult:
    payload: dict[str, Any] = op_input.payload or {}
    max_staleness_days = _read_max_staleness(payload)
    force = bool(payload.get("force", False))
    factory = get_sync_session_factory()

    with factory() as db:
        emit_event_sync(
            db,
            event_type=PatternEvents.decay_started.value,
            payload={"force": force, "max_staleness_days": max_staleness_days},
        )
        db.commit()

        now = utcnow()
        rows = db.execute(select(CanonicalPattern)).scalars().all()

        evaluated = 0
        demoted = 0
        deprecated = 0
        for pattern in rows:
            outcome = evaluate(
                pattern,
                now=now,
                max_staleness_days=max_staleness_days,
                force=force,
            )
            evaluated += 1
            changed_tier = outcome.new_tier != outcome.previous_tier
            pattern.staleness_score = outcome.new_staleness
            if changed_tier:
                pattern.trust_tier = outcome.new_tier
                if outcome.demoted:
                    demoted += 1
                    emit_event_sync(
                        db,
                        event_type=PatternEvents.demoted.value,
                        payload={
                            "pattern_id": outcome.pattern_id,
                            "previous_tier": outcome.previous_tier,
                            "new_tier": outcome.new_tier,
                            "staleness_score": outcome.new_staleness,
                        },
                    )
                if outcome.deprecated:
                    deprecated += 1
                    emit_event_sync(
                        db,
                        event_type=PatternEvents.deprecated.value,
                        payload={
                            "pattern_id": outcome.pattern_id,
                            "previous_tier": outcome.previous_tier,
                            "staleness_score": outcome.new_staleness,
                        },
                    )

        _touch_periodic_state(db, op_input.job_id, now)

        emit_event_sync(
            db,
            event_type=PatternEvents.decay_completed.value,
            payload={
                "evaluated": evaluated,
                "demoted": demoted,
                "deprecated": deprecated,
                "max_staleness_days": max_staleness_days,
            },
        )
        db.commit()

    return OperatorResult(
        success=True,
        summary=f"evaluated {evaluated} patterns ({demoted} demoted, {deprecated} deprecated)",
    )


def _touch_periodic_state(db, job_id: UUID, now) -> None:
    state = db.get(PeriodicJobState, JOB_KIND)
    if state is None:
        state = PeriodicJobState(job_kind=JOB_KIND, last_job_id=job_id, last_completed_at=now)
        db.add(state)
    else:
        state.last_job_id = job_id
        state.last_completed_at = now
    db.flush()
