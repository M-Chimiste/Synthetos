from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from libs.core.policy import TokenScope
from libs.core.state_machine import CycleStatus


class ResearchCharter(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    title: str
    problem_statement: str
    success_criteria: dict[str, Any]
    budget_envelope: dict[str, Any]
    source_scope: dict[str, Any]
    stop_conditions: dict[str, Any]
    constraints: dict[str, Any]
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class ResearchStateSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    state: CycleStatus
    transition_reason: str
    context: dict[str, Any]
    actor_id: str
    scope_used: str | None = None
    created_at: datetime


class ResearchCycle(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    current_status: CycleStatus
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    operator_name: str
    status: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    claimed_by: str | None
    lease_expires_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class DomainEventEnvelope(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence_id: int
    public_id: str
    cycle_public_id: str | None = None
    job_public_id: str | None = None
    actor_id: str
    scope_used: str | None = None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class SkillDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    skill_key: str
    phase: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SkillVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    version: str
    content_hash: str
    manifest: dict[str, Any]
    body_markdown: str
    hook_exports: list[str]
    is_valid: bool
    created_at: datetime
    updated_at: datetime


class SkillBinding(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    operator_name: str
    binding_reason: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SkillExecutionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    operator_name: str
    status: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class OrchestratorClient(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ModelRouteConfig(BaseModel):
    id: str
    role: str
    provider: str
    base_url: str
    model: str
    api_key_env: str | None = None
    timeout_seconds: int = 10


class ModelInvocationRecord(BaseModel):
    route_id: str
    model_id: str
    prompt_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)


class TokenScopeList(BaseModel):
    scopes: list[TokenScope]

