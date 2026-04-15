"""Skill and model call lineage recording.

Phase 3 operators use these helpers to write SkillBinding and
ModelCallRecord rows. Phase 6 adds runtime trust-tier enforcement here:
this is the real binding boundary, so blocking a binding at this call
prevents the skill's prompt/content from influencing the operator.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import SkillRuntimeEvents
from libs.core.events import emit_event_sync
from libs.schemas.model_gateway import CompletionResponse
from libs.skills.enforcement import SkillTrustViolation
from libs.skills.enforcement import evaluate as evaluate_skill_binding
from libs.storage.models.lineage import ModelCallRecord
from libs.storage.models.research import ResearchCycle
from libs.storage.models.skills import SkillBinding, SkillDefinition


def record_skill_usage(
    session: Session,
    *,
    skill_id: str,
    cycle_id: UUID,
    operator_type: str,
    job_id: UUID,
    config: dict[str, Any] | None = None,
    raise_on_block: bool = False,
) -> UUID | None:
    """Record a SkillBinding row after runtime trust enforcement.

    Looks up the skill's trust tier + manifest and evaluates it against the
    current cycle's policy. On violation: emits ``skill.blocked`` and returns
    None (or raises ``SkillTrustViolation`` when ``raise_on_block=True``).
    On success: emits ``skill.invoked`` when elevated capabilities are
    declared, then creates the ``SkillBinding`` row.

    Returns the binding ID, or None if the skill definition was not found or
    was blocked by policy (non-raising).
    """
    result = session.execute(
        select(SkillDefinition).where(SkillDefinition.skill_id == skill_id)
    )
    skill_def = result.scalar_one_or_none()
    if skill_def is None:
        return None

    cycle = session.get(ResearchCycle, cycle_id)
    cycle_config = (cycle.config if cycle is not None else None) or {}

    decision = evaluate_skill_binding(
        skill_id=skill_id,
        trust_tier=skill_def.trust_tier,
        manifest=skill_def.manifest,
        cycle_config=cycle_config,
    )
    if not decision.allowed:
        emit_event_sync(
            session,
            event_type=SkillRuntimeEvents.blocked.value,
            cycle_id=cycle_id,
            payload={
                "skill_id": skill_id,
                "trust_tier": str(skill_def.trust_tier),
                "reason": decision.reason,
                "operator_type": operator_type,
                "job_id": str(job_id),
            },
        )
        if raise_on_block:
            raise SkillTrustViolation(skill_id=skill_id, reason=decision.reason)
        return None

    if decision.elevated:
        emit_event_sync(
            session,
            event_type=SkillRuntimeEvents.invoked.value,
            cycle_id=cycle_id,
            payload={
                "skill_id": skill_id,
                "trust_tier": str(skill_def.trust_tier),
                "operator_type": operator_type,
                "job_id": str(job_id),
            },
        )

    binding = SkillBinding(
        id=uuid7(),
        skill_def_id=skill_def.id,
        cycle_id=cycle_id,
        operator_type=operator_type,
        bound_at=utcnow(),
        config=config,
    )
    session.add(binding)
    return binding.id


def record_model_call(
    session: Session,
    *,
    cycle_id: UUID | None,
    job_id: UUID | None,
    role: str,
    response: CompletionResponse | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> UUID:
    """Record a ModelCallRecord after an LLM completion.

    Returns the record ID.
    """
    record = ModelCallRecord(
        id=uuid7(),
        cycle_id=cycle_id,
        job_id=job_id,
        provider=provider or (response.provider if response is not None else "unknown"),
        model_id=model_id or (response.model if response is not None else "unknown"),
        role=role,
        input_tokens=input_tokens if input_tokens is not None else (
            response.input_tokens if response is not None else None
        ),
        output_tokens=output_tokens if output_tokens is not None else (
            response.output_tokens if response is not None else None
        ),
        created_at=utcnow(),
    )
    session.add(record)
    return record.id
