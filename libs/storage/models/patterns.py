"""Phase 6 canonical pattern memory SQLAlchemy models.

* ``canonical_patterns`` -- distilled cross-cycle/cross-charter patterns.
* ``pattern_observations`` -- lineage rows linking patterns to source artifacts.
* ``pattern_approvals`` -- curation decisions for non-auto patterns.
* ``periodic_job_state`` -- last-run bookkeeping for worker-periodic jobs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class CanonicalPattern(Base):
    """A distilled pattern consolidated from observed artifacts across cycles."""

    __tablename__ = "canonical_patterns"
    __table_args__ = (
        UniqueConstraint(
            "pattern_type", "content_key", name="uq_canonical_patterns_type_key"
        ),
        Index("ix_canonical_patterns_type", "pattern_type"),
        Index("ix_canonical_patterns_trust", "trust_tier"),
        Index("ix_canonical_patterns_last_reinforced", "last_reinforced_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    pattern_type: Mapped[str] = mapped_column(String(50))
    content_key: Mapped[str] = mapped_column(String(128))

    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text)
    structured_body: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)

    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    trust_tier: Mapped[str] = mapped_column(String(20), default="auto")

    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_reinforced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    staleness_score: Mapped[float] = mapped_column(Float, default=0.0)

    source_charter_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list
    )
    consolidation_version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class PatternObservation(Base):
    """Lineage row linking a canonical pattern to a source artifact that reinforced it."""

    __tablename__ = "pattern_observations"
    __table_args__ = (
        Index("ix_pattern_observations_pattern", "pattern_id"),
        Index("ix_pattern_observations_cycle", "cycle_id"),
        Index("ix_pattern_observations_charter", "charter_id"),
        UniqueConstraint(
            "pattern_id",
            "source_artifact_type",
            "source_artifact_id",
            name="uq_pattern_observations_artifact",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_patterns.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE")
    )
    source_artifact_type: Mapped[str] = mapped_column(String(50))
    source_artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    contribution: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(default=utcnow)


class PatternApproval(Base):
    """Curation decision for a pattern (approve/reject), scoped globally or per charter."""

    __tablename__ = "pattern_approvals"
    __table_args__ = (
        Index("ix_pattern_approvals_pattern", "pattern_id"),
        Index("ix_pattern_approvals_charter", "charter_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_patterns.id", ondelete="CASCADE")
    )
    charter_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(20))
    actor_type: Mapped[str] = mapped_column(String(50), default="user")
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rationale: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PeriodicJobState(Base):
    """Tracks last-run timestamp for worker-periodic jobs (decay, etc.).

    The worker uses this table to gate periodic job enqueues so only one tick
    per configured interval produces a new job.
    """

    __tablename__ = "periodic_job_state"

    job_kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
