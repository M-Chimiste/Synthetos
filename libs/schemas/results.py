"""Schemas for cycle and goal result introspection."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

PublicationReadiness = Literal["ready", "needs_review", "incomplete", "failed"]


class RunArtifactRead(BaseModel):
    artifact_id: str
    run_id: UUID
    name: str
    path: str
    size_bytes: int | None = None
    hash: str | None = None
    artifact_type: str
    download_url: str


class GoalRunResult(BaseModel):
    run_id: UUID
    experiment_spec_id: UUID
    attempt_number: int | None = None
    cycle_id: UUID
    run_number: int
    status: str
    title: str | None = None
    image_ref: str | None = None
    command: str | None = None
    gpu_enabled: bool | None = None
    exit_code: int | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[RunArtifactRead] = Field(default_factory=list)
    verification_verdict: str | None = None
    verification_summary: str | None = None
    verification_warnings: list[str] = Field(default_factory=list)
    failure_class: str | None = None
    error: str | None = None


class GoalAttemptResult(BaseModel):
    attempt_id: UUID | None = None
    attempt_number: int | None = None
    cycle_id: UUID
    status: str | None = None
    evaluation: dict[str, Any] | None = None
    introspection_markdown_path: str | None = None
    introspection_json_path: str | None = None
    cycle_report_path: str | None = None
    runs: list[GoalRunResult] = Field(default_factory=list)


class CycleResultIntrospection(BaseModel):
    cycle_id: UUID
    charter_id: UUID | None = None
    goal_id: UUID | None = None
    publication_readiness: PublicationReadiness
    summary: str
    interpretation: str
    caveats: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    completion_report_path: str | None = None
    completion_report_json_path: str | None = None
    introspection_markdown_path: str | None = None
    introspection_json_path: str | None = None
    runs: list[GoalRunResult] = Field(default_factory=list)
    metrics: dict[str, list[Any]] = Field(default_factory=dict)
    model_artifacts: list[RunArtifactRead] = Field(default_factory=list)
    remediation_history: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: str


class GoalResultSummary(BaseModel):
    goal_id: UUID
    charter_id: UUID
    title: str
    status: str
    publication_readiness: PublicationReadiness
    summary: str
    interpretation: str
    caveats: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    status_ledger: dict[str, Any] | None = None
    attempts: list[GoalAttemptResult] = Field(default_factory=list)
    metrics: dict[str, list[Any]] = Field(default_factory=dict)
    model_artifacts: list[RunArtifactRead] = Field(default_factory=list)
    remediation_history: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: str
