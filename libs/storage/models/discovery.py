"""Discovery-pipeline SQLAlchemy models.

These tables hold the per-cycle state of a Phase 1 discovery run:

* ``problem_profiles`` -- the scoped problem statement, source-scope, view
  preference, rerank policy, and cycle-level budget for one discovery session.
* ``discovery_sessions`` -- the running discovery loop attached to a cycle,
  with status, stats, and a structured step log.
* ``discovery_evaluations`` -- optional Recall@K / Precision@K / MRR rows
  attached to a session when ground-truth labels are supplied.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.core.clock import utcnow
from libs.storage.base import Base

if TYPE_CHECKING:
    from libs.storage.models.papers import PaperCard


class ProblemProfile(Base):
    """Scoped problem definition that drives one discovery session.

    A profile is created per cycle. Multiple profiles per cycle are not
    supported in Phase 1.
    """

    __tablename__ = "problem_profiles"
    __table_args__ = (
        Index("ix_problem_profiles_cycle", "cycle_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    query_text: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    source_scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    view_preference: Mapped[str] = mapped_column(String(32), default="both")
    rerank_policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    budget: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class DiscoverySession(Base):
    """One run of the Phase 1 discovery pipeline against a problem profile."""

    __tablename__ = "discovery_sessions"
    __table_args__ = (
        Index("ix_discovery_sessions_cycle_created", "cycle_id", "created_at"),
        Index("ix_discovery_sessions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("problem_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), default="created")
    view: Mapped[str] = mapped_column(String(32), default="both")
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    step_log: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    report_artifact_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    papers: Mapped[list[PaperCard]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


class DiscoveryEvaluation(Base):
    """Optional ground-truth metric attached to a discovery session."""

    __tablename__ = "discovery_evaluations"
    __table_args__ = (
        Index("ix_discovery_evaluations_session", "session_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric: Mapped[str] = mapped_column(String(50))
    k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value: Mapped[float] = mapped_column(Numeric(10, 6))
    source: Mapped[str] = mapped_column(String(50), default="user_supplied")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
