from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from libs.schemas.domain import (
    ArxivPaper,
    ArxivSyncRun,
    DomainEventEnvelope,
    EvidenceCard,
    ExperimentSpec,
    FailurePostmortem,
    HypothesisCard,
    JobRecord,
    PaperCard,
    ResearchCharter,
    ResearchCycle,
    ResearchStateSnapshot,
    RunArtifactManifest,
    RunRecord,
    RunTelemetryEvent,
    ScreeningDecision,
    SkillBinding,
    SkillDefinition,
    SkillExecutionRecord,
    SkillVersion,
    SourceRetrievalSession,
    VerificationReport,
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
    command: Literal[
        "pause", "cancel", "resume", "start_intake",
        "start_evidence", "request_hypothesis_review", "request_protocol_compilation",
    ]
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
    quality_metadata: dict[str, Any] = Field(default_factory=dict)


class TimelineEntry(BaseModel):
    timestamp: datetime
    event_type: str
    category: Literal["state_change", "operator", "run", "report", "user_action", "system"]
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class TimelineResponse(BaseModel):
    cycle_public_id: str
    items: list[TimelineEntry]


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


class PaperSearchHit(BaseModel):
    paper: ArxivPaper
    hybrid_score: float
    vector_score: float | None = None
    lexical_score: float | None = None


class PaperSearchResponse(BaseModel):
    items: list[PaperSearchHit]
    total: int
    sync_runs: list[ArxivSyncRun] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 2 — Evidence, Hypotheses, Experiment Specs
# ---------------------------------------------------------------------------


class EvidenceCardSummary(BaseModel):
    public_id: str
    paper_public_id: str
    claim: str
    evidence_type: str
    strength: str
    relevance_score: float
    read_depth: str
    created_at: datetime


class EvidenceCardDetail(EvidenceCard):
    pass


class EvidenceListResponse(BaseModel):
    items: list[EvidenceCardSummary]
    total: int


class EvidenceSummaryResponse(BaseModel):
    total_evidence: int
    by_type: dict[str, int]
    by_strength: dict[str, int]
    conflicts_detected: int
    redundancies_detected: int


class HypothesisCardSummary(BaseModel):
    public_id: str
    title: str
    portfolio_rank: int | None = None
    portfolio_score: float | None = None
    status: str
    novelty_score: float | None = None
    feasibility_score: float | None = None
    impact_score: float | None = None
    created_at: datetime


class HypothesisCardDetail(HypothesisCard):
    evidence_cards: list[EvidenceCardSummary] = Field(default_factory=list)


class HypothesisListResponse(BaseModel):
    items: list[HypothesisCardSummary]
    total: int


class PortfolioRankingResponse(BaseModel):
    cycle_public_id: str
    hypotheses: list[HypothesisCardSummary]
    ranking_method: str
    total: int


class ExperimentSpecSummary(BaseModel):
    public_id: str
    hypothesis_public_id: str
    title: str
    status: str
    gpu_required: bool
    estimated_runtime_minutes: int | None = None
    created_at: datetime


class ExperimentSpecDetail(ExperimentSpec):
    hypothesis: HypothesisCardSummary | None = None


class ExperimentSpecListResponse(BaseModel):
    items: list[ExperimentSpecSummary]
    total: int


class RunCreateRequest(BaseModel):
    execution_profile: str = "cpu-small"
    force_start: bool = False
    env_overrides: dict[str, str] = Field(default_factory=dict)


class RunCommandRequest(BaseModel):
    command: Literal["pause", "cancel", "retry", "resume"]


class RunSummary(BaseModel):
    public_id: str
    experiment_spec_public_id: str
    status: str
    execution_profile: str
    failure_classification: str | None = None
    verification_outcome: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Phase 4 — Verification & Postmortems
# ---------------------------------------------------------------------------


class VerificationReportSummary(BaseModel):
    public_id: str
    run_public_id: str
    experiment_spec_public_id: str
    outcome: str
    reviewer_summary: str
    created_at: datetime


class VerificationReportDetail(VerificationReport):
    """Full verification report including all check results."""

    pass


class VerificationReportListResponse(BaseModel):
    items: list[VerificationReportSummary]
    total: int


class FailurePostmortemSummary(BaseModel):
    public_id: str
    run_public_id: str
    failure_class: str
    failure_stage: str
    root_cause_summary: str
    created_at: datetime


class FailurePostmortemDetail(FailurePostmortem):
    """Full postmortem with remediation hints."""

    pass


class FailurePostmortemListResponse(BaseModel):
    items: list[FailurePostmortemSummary]
    total: int


class RunDetailResponse(BaseModel):
    run: RunRecord
    artifact_manifest: RunArtifactManifest | None = None
    telemetry_events: list[RunTelemetryEvent] = Field(default_factory=list)
    skill_execution_records: list[SkillExecutionRecord] = Field(default_factory=list)
    reports: list[ReportSummary] = Field(default_factory=list)
    verification_report: VerificationReportSummary | None = None
    postmortem: FailurePostmortemSummary | None = None


class RunListResponse(BaseModel):
    items: list[RunSummary]
    total: int


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime


class HistoricalComparisonResponse(BaseModel):
    run_public_id: str
    experiment_spec_public_id: str
    hypothesis_public_id: str | None = None
    charter_public_id: str | None = None
    comparison_scope: str = "same_charter"
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    memory_references: list[dict[str, Any]] = Field(default_factory=list)
    total_prior_runs: int


class NextStepRecommendation(BaseModel):
    recommendation_type: str
    rationale: str
    payload: dict[str, Any] = Field(default_factory=dict)


class VerificationSummaryResponse(BaseModel):
    cycle_public_id: str
    total_runs: int
    robust_count: int
    tentative_count: int
    rejected_count: int
    invalid_count: int
    pending_count: int
    postmortem_count: int
    latest_cycle_summary_report_public_id: str | None = None
    next_step_recommendations: list[NextStepRecommendation] = Field(default_factory=list)
