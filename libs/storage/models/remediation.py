"""Phase 4 remediation, signal, and frontier SQLAlchemy models.

These tables support the auto-remediation loop, directional signal
classification, metric frontier tracking, and run recommendations:

* ``remediation_actions`` -- one row per remediation attempt on a failed run.
* ``directional_signals`` -- signal classification for successful runs.
* ``metric_frontiers`` -- best-known metric state per hypothesis line.
* ``run_recommendations`` -- next-step recommendation after each terminal run.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class RemediationAction(Base):
    """One remediation attempt for a failed run."""

    __tablename__ = "remediation_actions"
    __table_args__ = (
        Index("ix_remediation_actions_run", "run_record_id"),
        Index("ix_remediation_actions_cycle_spec", "cycle_id", "experiment_spec_id"),
        Index("ix_remediation_actions_retry", "retry_run_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("run_records.id", ondelete="CASCADE")
    )
    retry_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("run_records.id", ondelete="SET NULL"), nullable=True
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    experiment_spec_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiment_specs.id", ondelete="CASCADE")
    )
    failure_class: Mapped[str] = mapped_column(String(50))
    strategy: Mapped[str] = mapped_column(String(50))
    strategy_tier: Mapped[str] = mapped_column(String(20))  # "focused" or "broad"
    action_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    outcome: Mapped[str] = mapped_column(String(50))  # retry_created, skipped, exhausted
    attempt_number: Mapped[int] = mapped_column(Integer)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DirectionalSignal(Base):
    """Directional signal classification for a successful run."""

    __tablename__ = "directional_signals"
    __table_args__ = (
        UniqueConstraint("run_record_id", name="uq_directional_signals_run"),
        Index("ix_directional_signals_run", "run_record_id"),
        Index("ix_directional_signals_spec_created", "experiment_spec_id", "created_at"),
        Index("ix_directional_signals_cycle", "cycle_id"),
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
    experiment_spec_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiment_specs.id", ondelete="CASCADE")
    )
    signal: Mapped[str] = mapped_column(String(50))
    primary_metric_name: Mapped[str] = mapped_column(String(200))
    primary_metric_value: Mapped[float] = mapped_column(Float)
    primary_metric_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    primary_metric_direction: Mapped[str] = mapped_column(String(20))  # maximize/minimize
    constraint_metrics: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    history_window: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    reasoning: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class MetricFrontier(Base):
    """Best-known metric state per hypothesis line (charter + hypothesis card)."""

    __tablename__ = "metric_frontiers"
    __table_args__ = (
        UniqueConstraint("charter_id", "hypothesis_card_id", name="uq_metric_frontiers_line"),
        Index("ix_metric_frontiers_best_run", "best_run_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    hypothesis_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("hypothesis_cards.id", ondelete="CASCADE")
    )
    primary_metric_name: Mapped[str] = mapped_column(String(200))
    primary_metric_direction: Mapped[str] = mapped_column(String(20))
    best_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("run_records.id", ondelete="SET NULL")
    )
    best_experiment_spec_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiment_specs.id", ondelete="SET NULL")
    )
    best_metric_value: Mapped[float] = mapped_column(Float)
    best_achieved_at: Mapped[datetime] = mapped_column()
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    successful_runs: Mapped[int] = mapped_column(Integer, default=0)
    runs_since_improvement: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class RunRecommendation(Base):
    """Next-step recommendation after a terminal run."""

    __tablename__ = "run_recommendations"
    __table_args__ = (
        UniqueConstraint("run_record_id", name="uq_run_recommendations_run"),
        Index("ix_run_recommendations_run", "run_record_id"),
        Index("ix_run_recommendations_cycle", "cycle_id"),
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
    experiment_spec_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiment_specs.id", ondelete="CASCADE")
    )
    recommendation_type: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text)
    inputs_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
