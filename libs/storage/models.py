from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.storage.base import Base, TimestampMixin
from libs.storage.vector_type import EmbeddingVector


class ResearchCharterModel(TimestampMixin, Base):
    __tablename__ = "research_charters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    problem_statement: Mapped[str] = mapped_column(Text)
    success_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budget_envelope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stop_conditions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchCycleModel(TimestampMixin, Base):
    __tablename__ = "research_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    charter_id: Mapped[int] = mapped_column(ForeignKey("research_charters.id"))
    current_state_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_state_snapshots.id"), nullable=True
    )
    current_status: Mapped[str] = mapped_column(String(64), index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_completed_operator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_completed_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resume_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Budget limits (user-defined, copied from charter.budget_envelope)
    budget_max_compute_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    budget_max_total_runs: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    budget_max_wall_clock_hours: Mapped[float | None] = mapped_column(
        Float, nullable=True,
    )
    budget_max_runs_per_hypothesis: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )

    # Budget tracking (system-maintained)
    budget_used_compute_minutes: Mapped[float] = mapped_column(
        Float, default=0.0,
    )
    budget_used_run_count: Mapped[int] = mapped_column(Integer, default=0)
    budget_runs_per_hypothesis: Mapped[dict[str, int]] = mapped_column(
        JSON, default=dict,
    )

    # Autonomy mode (per-cycle, defaults from policy)
    autonomy_mode: Mapped[str] = mapped_column(
        String(32), default="supervised",
    )

    charter = relationship("ResearchCharterModel")
    current_state_snapshot = relationship(
        "ResearchStateSnapshotModel",
        foreign_keys=[current_state_snapshot_id],
    )


class ResearchStateSnapshotModel(Base):
    __tablename__ = "research_state_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    state: Mapped[str] = mapped_column(String(64), index=True)
    transition_reason: Mapped[str] = mapped_column(String(255))
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    actor_id: Mapped[str] = mapped_column(String(128))
    scope_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class JobModel(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_cycles.id"), nullable=True, index=True,
    )
    operator_name: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DomainEventModel(Base):
    __tablename__ = "domain_events"

    sequence_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_cycles.id"), nullable=True, index=True,
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True,
    )
    actor_id: Mapped[str] = mapped_column(String(128))
    scope_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC),
    )


class ReportBundleModel(TimestampMixin, Base):
    __tablename__ = "report_bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_cycles.id"), nullable=True, index=True,
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True,
    )
    report_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    artifact_path: Mapped[str] = mapped_column(String(512))
    report_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    quality_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Phase B — link writeups to runs and hypotheses
    run_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("run_records.id"), nullable=True, index=True,
    )
    hypothesis_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("hypothesis_cards.id"), nullable=True, index=True,
    )


class ApprovalEventModel(TimestampMixin, Base):
    __tablename__ = "approval_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_cycles.id"), nullable=True, index=True,
    )
    actor_id: Mapped[str] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SkillDefinitionModel(TimestampMixin, Base):
    __tablename__ = "skill_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    skill_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phase: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SkillVersionModel(TimestampMixin, Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("definition_id", "version", name="uq_skill_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("skill_definitions.id"), index=True)
    version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(128))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    body_markdown: Mapped[str] = mapped_column(Text)
    hooks_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hook_exports: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)


class SkillBindingModel(TimestampMixin, Base):
    __tablename__ = "skill_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    skill_version_id: Mapped[int] = mapped_column(ForeignKey("skill_versions.id"), index=True)
    operator_name: Mapped[str] = mapped_column(String(128))
    binding_reason: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SkillExecutionRecordModel(TimestampMixin, Base):
    __tablename__ = "skill_execution_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    run_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("run_records.id"), nullable=True, index=True
    )
    skill_binding_id: Mapped[int] = mapped_column(ForeignKey("skill_bindings.id"), index=True)
    operator_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SkillValidationIssueModel(TimestampMixin, Base):
    __tablename__ = "skill_validation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    skill_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("skill_definitions.id"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(String(512))
    severity: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OrchestratorClientModel(TimestampMixin, Base):
    __tablename__ = "orchestrator_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrchestratorTokenModel(TimestampMixin, Base):
    __tablename__ = "orchestrator_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("orchestrator_clients.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrchestratorCommandModel(TimestampMixin, Base):
    __tablename__ = "orchestrator_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("orchestrator_clients.id"), index=True,
    )
    cycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_cycles.id"), nullable=True, index=True,
    )
    actor_id: Mapped[str] = mapped_column(String(128))
    scope_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    command_name: Mapped[str] = mapped_column(String(128))
    target_resource: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ArxivPaperModel(TimestampMixin, Base):
    __tablename__ = "arxiv_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    arxiv_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(String(512))
    pdf_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    search_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(
        EmbeddingVector(768),
        nullable=True,
    )
    embedding_model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class ArxivSyncRunModel(TimestampMixin, Base):
    __tablename__ = "arxiv_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    requested_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor_updated_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    reembedded_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceRetrievalSessionModel(TimestampMixin, Base):
    __tablename__ = "source_retrieval_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    query_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(64), default="pending")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaperCardModel(TimestampMixin, Base):
    __tablename__ = "paper_cards"
    __table_args__ = (
        UniqueConstraint("cycle_id", "content_hash", name="uq_paper_card_dedup"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    retrieval_session_id: Mapped[int] = mapped_column(
        ForeignKey("source_retrieval_sessions.id"), index=True,
    )
    source_type: Mapped[str] = mapped_column(String(64))  # arxiv, internal_corpus, external
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    publication_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Lifecycle
    lifecycle_status: Mapped[str] = mapped_column(
        String(64), index=True, default="retrieved",
    )  # retrieved, screened, shortlisted, html_fetched, pdf_fetched, rejected

    # Triage
    triage_score: Mapped[float | None] = mapped_column(nullable=True)
    triage_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    triage_model_route: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Shortlist
    shortlist_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shortlist_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Escalation
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # html, pdf
    fulltext_artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Dedup
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)


class ScreeningDecisionModel(TimestampMixin, Base):
    __tablename__ = "screening_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    paper_card_id: Mapped[int] = mapped_column(ForeignKey("paper_cards.id"), index=True)
    decision: Mapped[str] = mapped_column(String(64))  # advance, reject, uncertain
    score: Mapped[float] = mapped_column()
    rationale: Mapped[str] = mapped_column(Text)
    model_route_id: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(255))
    batch_index: Mapped[int] = mapped_column(Integer, default=0)


# ---------------------------------------------------------------------------
# Phase 2 — Evidence, Hypotheses, Protocols
# ---------------------------------------------------------------------------


class EvidenceCardModel(TimestampMixin, Base):
    __tablename__ = "evidence_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    paper_card_id: Mapped[int] = mapped_column(ForeignKey("paper_cards.id"), index=True)

    # Core evidence fields
    claim: Mapped[str] = mapped_column(Text)
    evidence_type: Mapped[str] = mapped_column(String(64))
    # finding, method, metric, baseline, limitation, dataset
    strength: Mapped[str] = mapped_column(String(32))
    # strong, moderate, weak, anecdotal
    relevance_score: Mapped[float] = mapped_column()
    relevance_rationale: Mapped[str] = mapped_column(Text)

    # Provenance
    source_section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_depth: Mapped[str] = mapped_column(String(32), default="abstract")
    # abstract, fulltext_html, fulltext_pdf

    # Conflict and redundancy
    conflict_with: Mapped[list[str]] = mapped_column(JSON, default=list)
    redundant_with: Mapped[list[str]] = mapped_column(JSON, default=list)
    conflict_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM lineage
    model_route_id: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(255))


class HypothesisCardModel(TimestampMixin, Base):
    __tablename__ = "hypothesis_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)

    # Content
    title: Mapped[str] = mapped_column(String(512))
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    approach_summary: Mapped[str] = mapped_column(Text)

    # Evidence linkage
    supporting_evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    counter_evidence: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Portfolio ranking
    portfolio_rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    portfolio_score: Mapped[float | None] = mapped_column(nullable=True)
    ranking_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status lifecycle: generated, critiqued, approved, rejected, compiled
    status: Mapped[str] = mapped_column(String(64), index=True, default="generated")

    # Critique
    critique_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    novelty_score: Mapped[float | None] = mapped_column(nullable=True)
    feasibility_score: Mapped[float | None] = mapped_column(nullable=True)
    impact_score: Mapped[float | None] = mapped_column(nullable=True)
    critique_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # LLM lineage
    model_route_id: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(255))


class ExperimentSpecModel(TimestampMixin, Base):
    __tablename__ = "experiment_specs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    hypothesis_card_id: Mapped[int] = mapped_column(
        ForeignKey("hypothesis_cards.id"), index=True,
    )

    # Protocol definition
    title: Mapped[str] = mapped_column(String(512))
    objective: Mapped[str] = mapped_column(Text)
    baseline_description: Mapped[str] = mapped_column(Text)
    method_description: Mapped[str] = mapped_column(Text)

    # Structured protocol fields
    controls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metrics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    datasets: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    stop_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    expected_outputs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Validation: draft, valid, rejected, approved
    status: Mapped[str] = mapped_column(String(64), index=True, default="draft")
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resource estimates
    estimated_runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_required: Mapped[bool] = mapped_column(Boolean, default=False)
    resource_requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # LLM lineage
    model_route_id: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(255))


class ModelInvocationRecordModel(TimestampMixin, Base):
    __tablename__ = "model_invocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_cycles.id"), nullable=True, index=True,
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True,
    )
    run_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("run_records.id"), nullable=True, index=True,
    )
    route_id: Mapped[str] = mapped_column(String(128))
    model_id: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(255))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Phase 3 — Run execution
# ---------------------------------------------------------------------------


class RunRecordModel(TimestampMixin, Base):
    __tablename__ = "run_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    experiment_spec_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_specs.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(64), index=True)
    execution_profile: Mapped[str] = mapped_column(String(64), index=True)
    workspace_path: Mapped[str] = mapped_column(String(512))
    artifact_root: Mapped[str] = mapped_column(String(512))
    stdout_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stderr_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    patch_archive_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    base_commit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    base_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image: Mapped[str] = mapped_column(String(255))
    build_recipe: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    command: Mapped[list[str]] = mapped_column(JSON, default=list)
    env_vars: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    mounts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    hardware_profile: Mapped[str] = mapped_column(String(64))
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    memory_limit_mb: Mapped[int] = mapped_column(Integer)
    cpu_limit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gpu_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    network_mode: Mapped[str] = mapped_column(String(32), default="disabled")
    bound_skill_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    prompt_lineage: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model_lineage: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    latest_resource_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_completed_operator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_completed_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resume_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    remediation_count: Mapped[int] = mapped_column(Integer, default=0)
    is_remediated_run: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunTelemetryEventModel(Base):
    __tablename__ = "run_telemetry_events"

    sequence_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    run_record_id: Mapped[int] = mapped_column(ForeignKey("run_records.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    stream: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# ---------------------------------------------------------------------------
# Phase 4 — Verification & Postmortems
# ---------------------------------------------------------------------------


class VerificationReportModel(TimestampMixin, Base):
    __tablename__ = "verification_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    run_record_id: Mapped[int] = mapped_column(ForeignKey("run_records.id"), index=True)
    experiment_spec_id: Mapped[int] = mapped_column(
        ForeignKey("experiment_specs.id"), index=True
    )
    hypothesis_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("hypothesis_cards.id"), nullable=True, index=True
    )
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    outcome_rationale: Mapped[str] = mapped_column(Text)
    baseline_comparison: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    historical_comparisons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metric_sanity_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    artifact_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    output_contract_checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    leakage_signals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    split_validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rerun_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_summary: Mapped[str] = mapped_column(Text)
    model_route_id: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(255))

    # Phase B — Directional Signal
    directional_signal: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True,
    )
    directional_signal_detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    self_critic_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RemediationActionModel(TimestampMixin, Base):
    __tablename__ = "remediation_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    run_record_id: Mapped[int] = mapped_column(ForeignKey("run_records.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    failure_classification: Mapped[str] = mapped_column(String(64))
    prompt_mode: Mapped[str] = mapped_column(String(32))
    prompt_id: Mapped[str] = mapped_column(String(255))
    model_route_id: Mapped[str] = mapped_column(String(128))
    diagnosis: Mapped[str] = mapped_column(Text)
    fix_type: Mapped[str] = mapped_column(String(64))
    fix_description: Mapped[str] = mapped_column(Text)
    fix_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prior_attempts_summary: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    outcome: Mapped[str] = mapped_column(String(32), index=True)


class FailurePostmortemModel(TimestampMixin, Base):
    __tablename__ = "failure_postmortems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("research_cycles.id"), index=True)
    run_record_id: Mapped[int] = mapped_column(ForeignKey("run_records.id"), index=True)
    verification_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("verification_reports.id"), nullable=True, index=True
    )
    failure_class: Mapped[str] = mapped_column(String(64), index=True)
    failure_stage: Mapped[str] = mapped_column(String(64))
    root_cause_summary: Mapped[str] = mapped_column(Text)
    contributing_factors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    remediation_suggestions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    retrieval_hints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    protocol_update_hints: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    similar_prior_failures: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model_route_id: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(255))


class MetricFrontierModel(TimestampMixin, Base):
    """Best-known metric value per hypothesis line. One row per (hypothesis, metric) pair."""

    __tablename__ = "metric_frontiers"
    __table_args__ = (
        UniqueConstraint("hypothesis_card_id", "metric_name", name="uq_frontier_hypothesis_metric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hypothesis_card_id: Mapped[int] = mapped_column(
        ForeignKey("hypothesis_cards.id"), index=True,
    )
    charter_id: Mapped[int] = mapped_column(
        ForeignKey("research_charters.id"), index=True,
    )
    metric_name: Mapped[str] = mapped_column(String(128))
    best_value: Mapped[float] = mapped_column(Float)
    best_run_public_id: Mapped[str] = mapped_column(String(64))
    best_run_id: Mapped[int] = mapped_column(ForeignKey("run_records.id"))
    runs_since_improvement: Mapped[int] = mapped_column(Integer, default=0)
    last_updated_run_id: Mapped[int] = mapped_column(ForeignKey("run_records.id"))


# ---------------------------------------------------------------------------
# Phase D — Cross-Charter Procedural Memory
# ---------------------------------------------------------------------------


class CanonicalPatternModel(TimestampMixin, Base):
    """Distilled cross-charter pattern extracted from operational observations."""

    __tablename__ = "canonical_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    pattern_type: Mapped[str] = mapped_column(String(32), index=True)
    polarity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(256), index=True, default="")
    trigger_conditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    proven_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    disproven_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, index=True)
    staleness_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True, default="active")
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # Hybrid search support (mirrors ArxivPaperModel pattern)
    search_text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(
        EmbeddingVector(768), nullable=True,
    )
    embedding_model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class PatternConsolidationRunModel(TimestampMixin, Base):
    """Tracks a single consolidation run over cross-charter observations."""

    __tablename__ = "pattern_consolidation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="running")
    trigger: Mapped[str] = mapped_column(String(32))
    postmortems_scanned: Mapped[int] = mapped_column(Integer, default=0)
    runs_scanned: Mapped[int] = mapped_column(Integer, default=0)
    patterns_created: Mapped[int] = mapped_column(Integer, default=0)
    patterns_updated: Mapped[int] = mapped_column(Integer, default=0)
    patterns_decayed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
