"""Skill and model call lineage recording.

Phase 3 operators use these helpers to write SkillBinding and
ModelCallRecord rows, closing the lineage gap left by Phases 1-2.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.schemas.model_gateway import CompletionResponse
from libs.storage.models.lineage import ModelCallRecord
from libs.storage.models.skills import SkillBinding, SkillDefinition


def record_skill_usage(
    session: Session,
    *,
    skill_id: str,
    cycle_id: UUID,
    operator_type: str,
    job_id: UUID,
    config: dict[str, Any] | None = None,
) -> UUID | None:
    """Record a SkillBinding row when an operator loads and uses a skill.

    Returns the binding ID, or None if the skill definition was not found.
    """
    result = session.execute(
        select(SkillDefinition).where(SkillDefinition.skill_id == skill_id)
    )
    skill_def = result.scalar_one_or_none()
    if skill_def is None:
        return None

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
