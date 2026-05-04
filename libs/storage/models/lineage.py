"""Model call lineage record for tracking LLM usage."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class ModelCallRecord(Base):
    """Records each LLM call that produces durable output."""

    __tablename__ = "model_call_records"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(100))
    model_id: Mapped[str] = mapped_column(String(200))
    prompt_template_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
