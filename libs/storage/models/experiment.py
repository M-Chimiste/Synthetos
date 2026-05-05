"""Phase 3 experiment pipeline SQLAlchemy models.

These tables hold the state of the hypothesis-to-verification pipeline:

* ``hypothesis_sessions`` -- one hypothesis-generation run per cycle.
* ``hypothesis_cards`` -- individual candidate hypotheses with evidence lineage.
* ``experiment_specs`` -- compiled executable protocols for selected hypotheses.
* ``run_records`` -- individual execution runs of an experiment spec.
* ``run_telemetry`` -- high-frequency streaming telemetry for live UI.
* ``verification_reports`` -- baseline verification outcomes for completed runs.
* ``failure_postmortems`` -- structured post-failure analysis.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class HypothesisSession(Base):
    """One run of the hypothesis generation pipeline for a cycle."""

    __tablename__ = "hypothesis_sessions"
    __table_args__ = (
        Index("ix_hypothesis_sessions_cycle_created", "cycle_id", "created_at"),
        Index("ix_hypothesis_sessions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(50), default="created")
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    step_log: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class HypothesisCard(Base):
    """One candidate hypothesis linked to supporting evidence."""

    __tablename__ = "hypothesis_cards"
    __table_args__ = (
        Index("ix_hypothesis_cards_session", "hypothesis_session_id"),
        Index("ix_hypothesis_cards_charter_status", "charter_id", "status"),
        Index("ix_hypothesis_cards_cycle", "cycle_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    hypothesis_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("hypothesis_sessions.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500))
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    mechanism: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    critique: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    novelty_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feasibility_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="candidate")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ExperimentSpec(Base):
    """Compiled executable protocol for a selected hypothesis."""

    __tablename__ = "experiment_specs"
    __table_args__ = (
        Index("ix_experiment_specs_hypothesis", "hypothesis_card_id"),
        Index("ix_experiment_specs_cycle_status", "cycle_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    hypothesis_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("hypothesis_cards.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    baseline: Mapped[dict[str, Any]] = mapped_column(JSONB)
    controls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    metrics: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    expected_artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    stop_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    code_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    hardware_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    base_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    build_recipe: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    primary_metric_index: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class RunRecord(Base):
    """One execution of an ExperimentSpec."""

    __tablename__ = "run_records"
    __table_args__ = (
        Index("ix_run_records_spec", "experiment_spec_id"),
        Index("ix_run_records_cycle_status", "cycle_id", "status"),
        Index("ix_run_records_container", "container_id"),
        Index("ix_run_records_parent", "parent_run_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    experiment_spec_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiment_specs.id", ondelete="CASCADE")
    )
    parent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("run_records.id", ondelete="SET NULL"), nullable=True
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    run_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    workspace_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    env_vars: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    resource_limits: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    stderr_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metrics_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    artifact_manifest: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    resource_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class RunTelemetry(Base):
    """High-frequency streaming telemetry rows for a run."""

    __tablename__ = "run_telemetry"
    __table_args__ = (
        Index("ix_run_telemetry_run_ts", "run_record_id", "timestamp"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("run_records.id", ondelete="CASCADE")
    )
    timestamp: Mapped[datetime] = mapped_column(default=utcnow)
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class VerificationReport(Base):
    """Baseline verification outcome for a completed run."""

    __tablename__ = "verification_reports"
    __table_args__ = (
        Index("ix_verification_reports_run", "run_record_id"),
        Index("ix_verification_reports_cycle_verdict", "cycle_id", "verdict"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("run_records.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    directional_signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "directional_signals.id",
            ondelete="SET NULL",
            name="fk_verification_reports_directional_signal_directional_signals",
        ),
        nullable=True,
    )
    recommendation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("run_recommendations.id", ondelete="SET NULL"), nullable=True
    )
    verdict: Mapped[str] = mapped_column(String(50))
    baseline_comparison: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    artifact_checks: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    output_contract: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metric_sanity: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FailurePostmortem(Base):
    """Structured post-failure analysis for a run."""

    __tablename__ = "failure_postmortems"
    __table_args__ = (
        Index("ix_failure_postmortems_run", "run_record_id"),
        Index("ix_failure_postmortems_cycle", "cycle_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("run_records.id", ondelete="CASCADE")
    )
    verification_report_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("verification_reports.id", ondelete="SET NULL"), nullable=True
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    failure_class: Mapped[str] = mapped_column(String(50))
    root_cause: Mapped[str] = mapped_column(Text)
    contributing_factors: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    error_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
