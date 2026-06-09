"""Goal-oriented research models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class ResearchGoal(Base):
    """A charter-scoped objective pursued across one or more cycles."""

    __tablename__ = "research_goals"
    __table_args__ = (
        Index("ix_research_goals_charter_status", "charter_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500))
    goal_statement: Mapped[str] = mapped_column(Text)
    success_criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="created")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    report_json_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class GoalAttempt(Base):
    """One cycle attempt under a parent research goal."""

    __tablename__ = "goal_attempts"
    __table_args__ = (
        UniqueConstraint("goal_id", "attempt_number", name="uq_goal_attempts_number"),
        UniqueConstraint("cycle_id", name="uq_goal_attempts_cycle"),
        Index("ix_goal_attempts_goal", "goal_id"),
        Index("ix_goal_attempts_cycle", "cycle_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    goal_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_goals.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="running")
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    report_json_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
