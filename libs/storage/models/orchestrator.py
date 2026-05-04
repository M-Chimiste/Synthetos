"""Orchestrator client and API token SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.core.clock import utcnow
from libs.storage.base import Base


class OrchestratorClient(Base):
    """An external orchestrator client registered to use the API."""

    __tablename__ = "orchestrator_clients"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    tokens: Mapped[list[ApiToken]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class ApiToken(Base):
    """An API token granting scoped access to an orchestrator client."""

    __tablename__ = "api_tokens"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    client_id: Mapped[UUID] = mapped_column(
        ForeignKey("orchestrator_clients.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    client: Mapped[OrchestratorClient] = relationship(back_populates="tokens")
