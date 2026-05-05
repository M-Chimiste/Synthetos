"""Domain event SQLAlchemy model (append-only audit trail)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.core.types import ActorType
from libs.storage.base import Base


class DomainEvent(Base):
    """Append-only domain event for audit trail and telemetry streaming."""

    __tablename__ = "domain_events"
    __table_args__ = (
        Index("ix_domain_events_charter_created", "charter_id", "created_at"),
        Index("ix_domain_events_cycle_created", "cycle_id", "created_at"),
        Index("ix_domain_events_type", "event_type"),
        Index("ix_domain_events_created", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    charter_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_charters.id", ondelete="SET NULL"), nullable=True
    )
    cycle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actor_type: Mapped[ActorType] = mapped_column(
        String(50), default=ActorType.system
    )
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
