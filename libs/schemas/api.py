from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from libs.schemas.domain import (
    DomainEventEnvelope,
    JobRecord,
    ResearchCharter,
    ResearchCycle,
    ResearchStateSnapshot,
    SkillBinding,
    SkillDefinition,
    SkillExecutionRecord,
    SkillVersion,
)


class CreateCycleRequest(BaseModel):
    title: str
    problem_statement: str
    success_criteria: dict[str, Any]
    budget_envelope: dict[str, Any]
    source_scope: dict[str, Any]
    stop_conditions: dict[str, Any]
    constraints: dict[str, Any]
    notes: str | None = None


class CycleCommandRequest(BaseModel):
    command: Literal["pause", "cancel", "resume"]


class ReportSummary(BaseModel):
    public_id: str
    cycle_public_id: str | None = None
    report_type: str
    title: str
    artifact_path: str
    created_at: datetime


class ReportDetailResponse(ReportSummary):
    markdown: str


class CycleSummaryResponse(BaseModel):
    cycle: ResearchCycle
    charter: ResearchCharter
    state_snapshot: ResearchStateSnapshot | None


class CycleDetailResponse(BaseModel):
    cycle: ResearchCycle
    charter: ResearchCharter
    current_state_snapshot: ResearchStateSnapshot | None
    recent_jobs: list[JobRecord] = Field(default_factory=list)
    recent_events: list[DomainEventEnvelope] = Field(default_factory=list)
    bound_skills: list[SkillBinding] = Field(default_factory=list)
    skill_execution_records: list[SkillExecutionRecord] = Field(default_factory=list)
    reports: list[ReportSummary] = Field(default_factory=list)


class CycleListResponse(BaseModel):
    items: list[CycleSummaryResponse]


class JobDetailResponse(BaseModel):
    job: JobRecord


class JobListResponse(BaseModel):
    items: list[JobRecord]


class SkillSummaryResponse(BaseModel):
    definition: SkillDefinition
    latest_version: SkillVersion | None = None


class SkillDetailResponse(BaseModel):
    definition: SkillDefinition
    versions: list[SkillVersion]
    validation_issues: list[dict[str, Any]] = Field(default_factory=list)


class SkillListResponse(BaseModel):
    items: list[SkillSummaryResponse]


class ReportListResponse(BaseModel):
    items: list[ReportSummary]


class JobListEnvelope(BaseModel):
    items: list[JobRecord]


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime

