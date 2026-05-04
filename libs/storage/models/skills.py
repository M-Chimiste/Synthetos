"""Skill definition and binding SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.core.types import TrustTier
from libs.storage.base import Base


class SkillDefinition(Base):
    """A discovered and validated skill package."""

    __tablename__ = "skill_definitions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(200), unique=True)
    version: Mapped[str] = mapped_column(String(50), default="0.1.0")
    phase: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trust_tier: Mapped[TrustTier] = mapped_column(
        String(50), default=TrustTier.third_party_untrusted
    )
    manifest: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(default=utcnow)


class SkillBinding(Base):
    """A binding of a skill to a cycle or operator invocation."""

    __tablename__ = "skill_bindings"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    skill_def_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_definitions.id", ondelete="CASCADE")
    )
    cycle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="SET NULL"), nullable=True
    )
    operator_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bound_at: Mapped[datetime] = mapped_column(default=utcnow)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
