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
    run_public_id: str | None = None
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


# ---------------------------------------------------------------------------
# Phase 3 — Run Execution Lab
# ---------------------------------------------------------------------------


class RunSpec(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_path: str
    image: str
    build_recipe: dict[str, Any] = Field(default_factory=dict)
    command: list[str] = Field(default_factory=list)
    env_vars: dict[str, str] = Field(default_factory=dict)
    mounts: list[dict[str, Any]] = Field(default_factory=list)
    hardware_profile: str
    timeout_seconds: int
    memory_limit_mb: int
    cpu_limit: str | None = None
    gpu_enabled: bool = False
    network_mode: str = "disabled"
    artifact_output_path: str
    patch_archive_path: str | None = None


class RunTelemetryEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence_id: int
    public_id: str
    run_public_id: str
    event_type: str
    stream: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RunArtifactManifest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_public_id: str
    manifest_path: str
    metrics_path: str | None = None
    checkpoint_path: str | None = None
    predictions_path: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class RunRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    cycle_public_id: str
    experiment_spec_public_id: str
    status: str
    execution_profile: str
    run_spec: RunSpec
    workspace_path: str
    artifact_root: str
    stdout_path: str | None = None
    stderr_path: str | None = None
    patch_archive_path: str | None = None
    base_commit: str | None = None
    base_branch: str | None = None
    bound_skill_keys: list[str] = Field(default_factory=list)
    prompt_lineage: list[dict[str, Any]] = Field(default_factory=list)
    model_lineage: list[dict[str, Any]] = Field(default_factory=list)
    latest_resource_snapshot: dict[str, Any] = Field(default_factory=dict)
    metrics_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_manifest: dict[str, Any] = Field(default_factory=dict)
    failure_classification: str | None = None
    verification_outcome: str | None = None
    last_error: str | None = None
    exit_code: int | None = None
    attempt_count: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Phase 4 — Verification & Postmortems
# ---------------------------------------------------------------------------


class VerificationReport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    cycle_public_id: str
    run_public_id: str
    experiment_spec_public_id: str
    hypothesis_public_id: str | None = None
    outcome: str
    outcome_rationale: str
    baseline_comparison: dict[str, Any] = Field(default_factory=dict)
    historical_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    metric_sanity_checks: list[dict[str, Any]] = Field(default_factory=list)
    artifact_checks: list[dict[str, Any]] = Field(default_factory=list)
    output_contract_checks: list[dict[str, Any]] = Field(default_factory=list)
    leakage_signals: list[dict[str, Any]] = Field(default_factory=list)
    split_validation: dict[str, Any] = Field(default_factory=dict)
    rerun_note: str | None = None
    reviewer_summary: str
    model_route_id: str
    prompt_id: str
    directional_signal: str | None = None
    directional_signal_detail: dict[str, Any] = Field(default_factory=dict)
    self_critic_result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class FailurePostmortem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    cycle_public_id: str
    run_public_id: str
    verification_report_public_id: str | None = None
    failure_class: str
    failure_stage: str
    root_cause_summary: str
    contributing_factors: list[dict[str, Any]] = Field(default_factory=list)
    remediation_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_hints: list[dict[str, Any]] = Field(default_factory=list)
    protocol_update_hints: list[dict[str, Any]] = Field(default_factory=list)
    similar_prior_failures: list[dict[str, Any]] = Field(default_factory=list)
    model_route_id: str
    prompt_id: str
    created_at: datetime
    updated_at: datetime


class RemediationAction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    cycle_public_id: str
    run_public_id: str
    attempt_number: int
    failure_classification: str
    prompt_mode: str
    prompt_id: str
    model_route_id: str
    diagnosis: str
    fix_type: str
    fix_description: str
    fix_payload: dict[str, Any] = Field(default_factory=dict)
    prior_attempts_summary: list[dict[str, Any]] = Field(default_factory=list)
    outcome: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Phase B — Directional Signal Evaluation
# ---------------------------------------------------------------------------


class ConstraintMetric(BaseModel):
    """A constraint metric with bounds for multi-metric reconciliation."""

    name: str
    higher_is_better: bool = True
    lower_bound: float | None = None
    upper_bound: float | None = None


class SuccessCriteria(BaseModel):
    """Typed access to a charter's success_criteria JSON field."""

    primary_metric: str
    primary_higher_is_better: bool = True
    significance_threshold: float = 0.01
    stall_window: int = 3
    constraint_metrics: list[ConstraintMetric] = Field(default_factory=list)


class MetricFrontier(BaseModel):
    """Best-known metric value for a hypothesis line."""

    model_config = ConfigDict(from_attributes=True)

    public_id: str
    hypothesis_public_id: str
    metric_name: str
    best_value: float
    best_run_public_id: str
    runs_since_improvement: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# arXiv Warehouse
# ---------------------------------------------------------------------------


class ArxivPaper(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    arxiv_id: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    created_date: datetime | None = None
    updated_date: datetime | None = None
    doi: str | None = None
    source_url: str
    pdf_url: str | None = None
    search_text: str
    content_hash: str
    embedding_model_id: str | None = None
    embedding_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ArxivSyncRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    mode: str
    source: str
    status: str
    requested_from: datetime | None = None
    requested_until: datetime | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    cursor_updated_until: datetime | None = None
    inserted_count: int
    updated_count: int
    reembedded_count: int
    skipped_count: int
    error_message: str | None = None
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
