from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from libs.schemas.domain import (
    DomainEventEnvelope,
    JobRecord,
    PaperCard,
    ResearchCharter,
    ResearchCycle,
    ResearchStateSnapshot,
    ScreeningDecision,
    SkillBinding,
    SkillDefinition,
    SkillExecutionRecord,
    SkillVersion,
    SourceRetrievalSession,
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
    command: Literal["pause", "cancel", "resume", "start_intake"]
    payload: dict[str, Any] | None = None


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


class PaperCardSummary(BaseModel):
    public_id: str
    title: str
    source_type: str
    external_id: str
    lifecycle_status: str
    triage_score: float | None = None
    triage_rationale: str | None = None
    shortlist_rank: int | None = None
    shortlist_reason: str | None = None
    escalation_reason: str | None = None
    escalation_type: str | None = None
    retrieval_provenance_summary: list[str] = Field(default_factory=list)
    created_at: datetime


class PaperCardDetail(PaperCard):
    screening_decisions: list[ScreeningDecision] = Field(default_factory=list)
    retrieval_provenance_summary: list[str] = Field(default_factory=list)


class PaperListResponse(BaseModel):
    items: list[PaperCardSummary]
    total: int


class LiteratureTriageResponse(BaseModel):
    retrieval_sessions: list[SourceRetrievalSession]
    total_papers: int
    screened_count: int
    shortlisted_count: int
    escalated_count: int
    papers: list[PaperCardSummary]


class RetrievalSessionListResponse(BaseModel):
    items: list[SourceRetrievalSession]


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
