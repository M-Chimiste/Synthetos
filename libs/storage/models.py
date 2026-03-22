from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.storage.base import Base, TimestampMixin


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
    route_id: Mapped[str] = mapped_column(String(128))
    model_id: Mapped[str] = mapped_column(String(128))
    prompt_id: Mapped[str] = mapped_column(String(255))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
