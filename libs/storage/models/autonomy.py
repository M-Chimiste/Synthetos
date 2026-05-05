"""Phase 5 autonomy SQLAlchemy models.

* ``autonomy_budgets`` -- budget consumption tracking per cycle.
* ``loop_decisions`` -- audit log of every autonomous-loop decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class AutonomyBudget(Base):
    """Budget consumption tracking for one autonomous cycle."""

    __tablename__ = "autonomy_budgets"
    __table_args__ = (
        UniqueConstraint("cycle_id", name="uq_autonomy_budgets_cycle"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    wall_clock_elapsed_s: Mapped[float] = mapped_column(Float, default=0.0)
    runs_per_hypothesis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_run_completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class LoopDecision(Base):
    """Audit log of one autonomous-loop iteration decision."""

    __tablename__ = "loop_decisions"
    __table_args__ = (
        Index("ix_loop_decisions_cycle", "cycle_id"),
        Index("ix_loop_decisions_run", "run_record_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    run_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("run_records.id", ondelete="CASCADE")
    )
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("run_recommendations.id", ondelete="SET NULL")
    )
    iteration_number: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(50))
    gate_triggered: Mapped[str | None] = mapped_column(String(100), nullable=True)
    budget_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    hypothesis_card_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hypothesis_cards.id", ondelete="SET NULL"), nullable=True
    )
    next_hypothesis_card_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("hypothesis_cards.id", ondelete="SET NULL"), nullable=True
    )
    next_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    context_summary_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    reasoning: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
