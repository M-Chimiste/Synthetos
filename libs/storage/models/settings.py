"""Runtime settings models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.core.clock import utcnow
from libs.storage.base import Base


class ModelCatalogEntry(Base):
    """Curated LLM model entry selectable from runtime settings."""

    __tablename__ = "model_catalog_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str] = mapped_column(String(300))
    provider_type: Mapped[str] = mapped_column(String(50))
    provider_name: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(300))
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_timeout_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    role_bindings: Mapped[list[ModelRoleBinding]] = relationship(back_populates="catalog_entry")


class ModelRoleBinding(Base):
    """Runtime override for a logical model role."""

    __tablename__ = "model_role_bindings"

    role: Mapped[str] = mapped_column(String(100), primary_key=True)
    catalog_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_catalog_entries.id", ondelete="RESTRICT")
    )
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeout_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    catalog_entry: Mapped[ModelCatalogEntry] = relationship(back_populates="role_bindings")
