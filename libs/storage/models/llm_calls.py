"""LLM call transcript: automatic per-call telemetry from the reliability layer.

Distinct from ModelCallRecord (lineage: calls that produced durable outputs,
recorded manually by operators). Every router call lands here with outcome,
attempts, latency, and token counts -- the observability needed to tune small
local models: which roles fail validation, how often truncation re-calls fire,
what latency each model actually delivers.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class LLMCall(Base):
    """One logical LLM call (including all its internal retry attempts)."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_role_created_at", "role", "created_at"),
        Index("ix_llm_calls_job_id", "job_id"),
        Index("ix_llm_calls_outcome", "outcome"),
        Index("ix_llm_calls_cycle_id", "cycle_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    cycle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(300))
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_kind: Mapped[str] = mapped_column(String(20))  # complete | structured
    response_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # sha256 of the canonical messages JSON; full messages stored only when
    # LAB_LLM_LOG_PROMPTS is enabled.
    messages_hash: Mapped[str] = mapped_column(String(64))
    messages: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Total wall clock across all attempts, in milliseconds.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    # success | validation_error | transport_error | timeout | truncated | cancelled | error
    outcome: Mapped[str] = mapped_column(String(30))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_log: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
