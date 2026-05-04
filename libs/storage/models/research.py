"""Research charter and cycle SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.core.clock import utcnow
from libs.core.types import CharterStatus, CycleStatus
from libs.storage.base import Base


class ResearchCharter(Base):
    """Top-level research project definition."""

    __tablename__ = "research_charters"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    problem_statement: Mapped[str] = mapped_column(Text, default="")
    source_scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[CharterStatus] = mapped_column(
        String(50), default=CharterStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    # Relationships
    cycles: Mapped[list[ResearchCycle]] = relationship(
        back_populates="charter", cascade="all, delete-orphan"
    )


class ResearchCycle(Base):
    """One bounded research loop within a charter."""

    __tablename__ = "research_cycles"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE")
    )
    status: Mapped[CycleStatus] = mapped_column(
        String(50), default=CycleStatus.created
    )
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    charter: Mapped[ResearchCharter] = relationship(back_populates="cycles")
