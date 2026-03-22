from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from libs.core.policy import Actor
from libs.core.state_machine import CycleStatus


class ContextPack(BaseModel):
    sources: list[str] = Field(default_factory=list)
    budget_tokens: int = 2000
    metadata: dict[str, Any] = Field(default_factory=dict)


class OperatorContext(BaseModel):
    cycle_public_id: str
    job_public_id: str
    actor_id: str
    current_state: CycleStatus
    charter: dict[str, Any]
    context_pack: ContextPack

    @classmethod
    def from_actor(
        cls,
        actor: Actor,
        cycle_public_id: str,
        job_public_id: str,
        current_state: CycleStatus,
        charter: dict[str, Any],
        context_pack: ContextPack,
    ) -> OperatorContext:
        return cls(
            cycle_public_id=cycle_public_id,
            job_public_id=job_public_id,
            actor_id=actor.actor_id,
            current_state=current_state,
            charter=charter,
            context_pack=context_pack,
        )


class StatePatch(BaseModel):
    target_state: CycleStatus
    reason: str
    context: dict[str, Any] = Field(default_factory=dict)


class NextAction(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class OperatorReport(BaseModel):
    title: str
    body_markdown: str
    prompt_id: str
    report_type: str = "operator_report"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SkillExecutionOutcome(BaseModel):
    skill_version_public_id: str
    skill_binding_public_id: str
    operator_name: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)


class OperatorResult(BaseModel):
    state_patch: StatePatch
    emitted_events: list[dict[str, Any]] = Field(default_factory=list)
    created_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    approvals_requested: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    operator_report: OperatorReport
    skill_execution_records: list[SkillExecutionOutcome] = Field(default_factory=list)
