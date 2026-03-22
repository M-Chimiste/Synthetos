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


class SourceRetrievalSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    source_type: str
    query_params: dict[str, Any]
    status: str
    result_count: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class PaperCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    source_type: str
    external_id: str
    title: str
    abstract: str | None = None
    authors: list[str]
    categories: list[str]
    publication_date: datetime | None = None
    source_url: str | None = None
    pdf_url: str | None = None
    metadata_extra: dict[str, Any] = Field(default_factory=dict)
    lifecycle_status: str
    triage_score: float | None = None
    triage_rationale: str | None = None
    shortlist_rank: int | None = None
    shortlist_reason: str | None = None
    escalation_reason: str | None = None
    escalation_type: str | None = None
    created_at: datetime
    updated_at: datetime


class ScreeningDecision(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    decision: str
    score: float
    rationale: str
    model_route_id: str
    prompt_id: str
    batch_index: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Phase 2 — Evidence, Hypotheses, Protocols
# ---------------------------------------------------------------------------


class EvidenceCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    paper_public_id: str
    claim: str
    evidence_type: str
    strength: str
    relevance_score: float
    relevance_rationale: str
    source_section: str | None = None
    source_quote: str | None = None
    read_depth: str
    conflict_with: list[str] = Field(default_factory=list)
    redundant_with: list[str] = Field(default_factory=list)
    conflict_notes: str | None = None
    model_route_id: str
    prompt_id: str
    created_at: datetime
    updated_at: datetime


class HypothesisCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    title: str
    statement: str
    rationale: str
    approach_summary: str
    supporting_evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    portfolio_rank: int | None = None
    portfolio_score: float | None = None
    ranking_rationale: str | None = None
    status: str
    critique_summary: str | None = None
    novelty_score: float | None = None
    feasibility_score: float | None = None
    impact_score: float | None = None
    critique_issues: list[dict[str, Any]] = Field(default_factory=list)
    model_route_id: str
    prompt_id: str
    created_at: datetime
    updated_at: datetime


class ExperimentSpec(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    hypothesis_public_id: str
    title: str
    objective: str
    baseline_description: str
    method_description: str
    controls: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    stop_conditions: list[dict[str, Any]] = Field(default_factory=list)
    expected_outputs: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)
    rejection_reason: str | None = None
    estimated_runtime_minutes: int | None = None
    gpu_required: bool = False
    resource_requirements: dict[str, Any] = Field(default_factory=dict)
    model_route_id: str
    prompt_id: str
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
    provider: str = "openai_compatible"  # openai_compatible | anthropic | google
    base_url: str
    model: str
    api_key_env: str | None = None
    timeout_seconds: int = 60
    supports_json_mode: bool = True
    priority: int = 0  # lower = preferred; enables fallback chains


class ModelInvocationRecord(BaseModel):
    route_id: str
    model_id: str
    prompt_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)


class TokenScopeList(BaseModel):
    scopes: list[TokenScope]

