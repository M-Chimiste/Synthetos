"""Pydantic schemas for the Phase 1 discovery pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RerankPolicy(BaseModel):
    """Per-cycle policy controlling reranker behavior."""

    enabled: bool = True
    top_n: int = Field(default=100, ge=1, le=1000)
    budget_seconds: float = Field(default=30.0, ge=0.0)
    model: str | None = None


class DiscoveryBudget(BaseModel):
    """Loose cycle-level budgets for the discovery pipeline."""

    max_internal_results: int = Field(default=200, ge=1, le=2000)
    max_external_results: int = Field(default=50, ge=0, le=1000)
    analyze_top_n: int = Field(default=25, ge=0, le=500)


class ProblemProfileCreate(BaseModel):
    """Body posted by ``POST /charters/{id}/discovery``."""

    query_text: str = Field(min_length=1, max_length=4000)
    notes: str = ""
    source_scope: dict[str, Any] | None = None
    view_preference: str = Field(default="both", pattern="^(stable|discovery|both)$")
    rerank_policy: RerankPolicy = Field(default_factory=RerankPolicy)
    budget: DiscoveryBudget = Field(default_factory=DiscoveryBudget)


class ProblemProfileRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    cycle_id: UUID
    query_text: str
    notes: str
    source_scope: dict[str, Any] | None
    view_preference: str
    rerank_policy: dict[str, Any] | None
    budget: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class DiscoverySessionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    cycle_id: UUID
    charter_id: UUID
    profile_id: UUID
    status: str
    view: str
    stats: dict[str, Any] | None
    step_log: list[Any] | None
    report_artifact_path: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class DiscoverySessionStartResponse(BaseModel):
    """Returned by ``POST /charters/{id}/discovery``."""

    session: DiscoverySessionRead
    profile: ProblemProfileRead
    job_id: UUID


class TriageRequest(BaseModel):
    """Body for the manual triage override endpoint."""

    triage_status: str = Field(pattern="^(discovered|shortlisted|dropped|escalated)$")
    triage_reason: str | None = None


class EvaluationSubmission(BaseModel):
    """Ground-truth labels submitted to compute Recall@K / Precision@K / MRR."""

    relevant_ids: list[str] = Field(min_length=1)
    k_values: list[int] = Field(default_factory=lambda: [10, 25])
    notes: str | None = None


class EvaluationMetricRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    session_id: UUID
    metric: str
    k: int | None
    value: float
    source: str
    notes: str | None
    created_at: datetime
