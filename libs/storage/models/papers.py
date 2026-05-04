"""PaperCard SQLAlchemy model.

A ``PaperCard`` is one candidate paper attached to a ``DiscoverySession``.
Cards unify rows from heterogeneous sources (internal arXiv mirror, live
arXiv API, future external sources) under a stable shape that downstream
operators can rank, rerank, analyze, and triage.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.core.clock import utcnow
from libs.storage.base import Base

if TYPE_CHECKING:
    from libs.storage.models.discovery import DiscoverySession


class PaperCard(Base):
    """A candidate paper inside a discovery session."""

    __tablename__ = "paper_cards"
    __table_args__ = (
        UniqueConstraint("session_id", "dedupe_key", name="uq_paper_cards_session_dedupe"),
        Index("ix_paper_cards_session_score", "session_id", "final_score"),
        Index("ix_paper_cards_charter_created", "charter_id", "created_at"),
        Index("ix_paper_cards_session_status", "session_id", "triage_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("discovery_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Source bookkeeping
    source: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str] = mapped_column(String(200))
    dedupe_key: Mapped[str] = mapped_column(String(200))

    # Denormalized metadata so cards from internal vs live sources unify
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str] = mapped_column(Text, default="")
    authors: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(256), nullable=True)
    year: Mapped[int | None] = mapped_column(nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    doi: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Optional copy of the embedding (when sourced from internal_corpus). Used
    # by MMR diversification on the Discovery view.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)

    # Scores produced through the pipeline
    bm25_score: Mapped[float | None] = mapped_column(nullable=True)
    dense_score: Mapped[float | None] = mapped_column(nullable=True)
    first_stage_score: Mapped[float | None] = mapped_column(nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(nullable=True)
    final_score: Mapped[float | None] = mapped_column(nullable=True)

    # View memberships -- e.g. ``["stable", "discovery"]``
    view_membership: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Triage state ("discovered" -> "shortlisted" / "dropped" / "escalated")
    triage_status: Mapped[str] = mapped_column(String(50), default="discovered")
    triage_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata-depth analysis packet (JSON of MetadataAnalysisPacket)
    metadata_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Phase 2: full-text analysis status
    analysis_status: Mapped[str] = mapped_column(String(50), default="not_analyzed")

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    session: Mapped["DiscoverySession"] = relationship(back_populates="papers")
