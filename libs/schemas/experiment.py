"""Phase 3 Pydantic schemas for hypotheses, protocols, execution, and verification."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Hypothesis session
# ---------------------------------------------------------------------------


class HypothesisBudget(BaseModel):
    """Budget constraints for hypothesis generation."""

    max_hypotheses: int = Field(default=10, ge=1, le=50)
    max_critique_rounds: int = Field(default=2, ge=1, le=5)


class HypothesisSessionStartRequest(BaseModel):
    """Request to start a hypothesis generation session."""

    cycle_id: UUID
    charter_id: UUID
    budget: HypothesisBudget = Field(default_factory=HypothesisBudget)


class HypothesisSessionRead(BaseModel):
    """Read model for a hypothesis session."""

    model_config = {"from_attributes": True}

    id: UUID
    cycle_id: UUID
    charter_id: UUID
    status: str
    budget: dict[str, Any] | None = None
    stats: dict[str, Any] | None = None
    step_log: list[Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class HypothesisSessionStartResponse(BaseModel):
    """Response after starting a hypothesis session."""

    session: HypothesisSessionRead
    job_id: UUID


# ---------------------------------------------------------------------------
# Hypothesis card
# ---------------------------------------------------------------------------


class HypothesisCardRead(BaseModel):
    """Read model for a hypothesis card."""

    model_config = {"from_attributes": True}

    id: UUID
    hypothesis_session_id: UUID
    charter_id: UUID
    cycle_id: UUID
    title: str
    statement: str
    rationale: str
    mechanism: str | None = None
    supporting_evidence_ids: list[str]
    critique: dict[str, Any] | None = None
    novelty_score: float | None = None
    feasibility_score: float | None = None
    impact_score: float | None = None
    rank: int | None = None
    status: str
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class HypothesisCardUpdate(BaseModel):
    """Update model for a hypothesis card (select/reject/defer)."""

    status: str | None = Field(
        default=None,
        pattern="^(candidate|selected|rejected|deferred)$",
    )
    rejection_reason: str | None = None


# ---------------------------------------------------------------------------
# Experiment spec
# ---------------------------------------------------------------------------


class ExperimentSpecCompileRequest(BaseModel):
    """Request to compile protocols for selected hypotheses."""

    cycle_id: UUID
    charter_id: UUID
    hypothesis_card_ids: list[UUID] | None = Field(
        default=None,
        description="Specific cards to compile. If None, compiles top-ranked.",
    )
    hardware_profile: dict[str, Any] | None = None
    base_image: str | None = None


class ExperimentSpecRead(BaseModel):
    """Read model for an experiment spec."""

    model_config = {"from_attributes": True}

    id: UUID
    hypothesis_card_id: UUID
    charter_id: UUID
    cycle_id: UUID
    title: str
    description: str
    baseline: dict[str, Any]
    controls: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    expected_artifacts: list[dict[str, Any]]
    stop_conditions: list[dict[str, Any]]
    code_plan: dict[str, Any] | None = None
    hardware_profile: dict[str, Any] | None = None
    base_image: str | None = None
    build_recipe: dict[str, Any] | None = None
    status: str
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class ExperimentSpecCompileResponse(BaseModel):
    """Response after compiling protocols."""

    specs: list[ExperimentSpecRead]
    job_id: UUID


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------


class RunStartRequest(BaseModel):
    """Request to start an experiment run."""

    experiment_spec_id: UUID
    gpu_enabled: bool = False


class RunControlRequest(BaseModel):
    """Request to control a running experiment."""

    action: str = Field(pattern="^(pause|resume|cancel|retry)$")


class RunRecordRead(BaseModel):
    """Read model for a run record."""

    model_config = {"from_attributes": True}

    id: UUID
    experiment_spec_id: UUID
    charter_id: UUID
    cycle_id: UUID
    run_number: int
    status: str
    workspace_path: str | None = None
    container_id: str | None = None
    image_ref: str | None = None
    command: str | None = None
    env_vars: dict[str, Any] | None = None
    resource_limits: dict[str, Any] | None = None
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    metrics_output: dict[str, Any] | None = None
    artifact_manifest: list[dict[str, Any]] | None = None
    resource_usage: dict[str, Any] | None = None
    failure_class: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RunStartResponse(BaseModel):
    """Response after starting a run."""

    run: RunRecordRead
    job_id: UUID


# ---------------------------------------------------------------------------
# Run telemetry
# ---------------------------------------------------------------------------


class RunTelemetryRead(BaseModel):
    """Read model for a telemetry row."""

    model_config = {"from_attributes": True}

    id: UUID
    run_record_id: UUID
    timestamp: datetime
    event_type: str
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Verification report
# ---------------------------------------------------------------------------


class VerificationReportRead(BaseModel):
    """Read model for a verification report."""

    model_config = {"from_attributes": True}

    id: UUID
    run_record_id: UUID
    charter_id: UUID
    cycle_id: UUID
    verdict: str
    baseline_comparison: dict[str, Any] | None = None
    artifact_checks: list[dict[str, Any]] | None = None
    output_contract: dict[str, Any] | None = None
    metric_sanity: dict[str, Any] | None = None
    warnings: list[str] | None = None
    summary: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Failure postmortem
# ---------------------------------------------------------------------------


class FailurePostmortemRead(BaseModel):
    """Read model for a failure postmortem."""

    model_config = {"from_attributes": True}

    id: UUID
    run_record_id: UUID
    verification_report_id: UUID | None = None
    charter_id: UUID
    cycle_id: UUID
    failure_class: str
    root_cause: str
    contributing_factors: list[dict[str, Any]] | None = None
    error_trace: str | None = None
    next_step_recommendation: str | None = None
    lessons: list[dict[str, Any]] | None = None
    created_at: datetime
