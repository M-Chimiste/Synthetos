"""Phase 4 Pydantic schemas for remediation, signals, frontiers, and recommendations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Remediation action
# ---------------------------------------------------------------------------


class RemediationActionRead(BaseModel):
    """Read model for a remediation action."""

    model_config = {"from_attributes": True}

    id: UUID
    run_record_id: UUID
    retry_run_id: UUID | None = None
    charter_id: UUID
    cycle_id: UUID
    experiment_spec_id: UUID
    failure_class: str
    strategy: str
    strategy_tier: str
    action_detail: dict[str, Any] | None = None
    outcome: str
    attempt_number: int
    max_attempts: int
    reasoning: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Directional signal
# ---------------------------------------------------------------------------


class DirectionalSignalRead(BaseModel):
    """Read model for a directional signal."""

    model_config = {"from_attributes": True}

    id: UUID
    run_record_id: UUID
    charter_id: UUID
    cycle_id: UUID
    experiment_spec_id: UUID
    signal: str
    primary_metric_name: str
    primary_metric_value: float
    primary_metric_delta: float | None = None
    primary_metric_direction: str
    constraint_metrics: list[dict[str, Any]] | None = None
    history_window: list[dict[str, Any]] | None = None
    reasoning: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Metric frontier
# ---------------------------------------------------------------------------


class MetricFrontierRead(BaseModel):
    """Read model for a metric frontier."""

    model_config = {"from_attributes": True}

    id: UUID
    charter_id: UUID
    hypothesis_card_id: UUID
    primary_metric_name: str
    primary_metric_direction: str
    best_run_id: UUID
    best_experiment_spec_id: UUID
    best_metric_value: float
    best_achieved_at: datetime
    total_runs: int
    successful_runs: int
    runs_since_improvement: int
    updated_at: datetime
    created_at: datetime


# ---------------------------------------------------------------------------
# Run recommendation
# ---------------------------------------------------------------------------


class RunRecommendationRead(BaseModel):
    """Read model for a run recommendation."""

    model_config = {"from_attributes": True}

    id: UUID
    run_record_id: UUID
    charter_id: UUID
    cycle_id: UUID
    experiment_spec_id: UUID
    recommendation_type: str
    action: str
    reasoning: str
    inputs_summary: dict[str, Any] | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Run lineage
# ---------------------------------------------------------------------------


class RunLineageRead(BaseModel):
    """Full retry chain for a run."""

    run_ids: list[UUID]
    remediation_actions: list[RemediationActionRead]
