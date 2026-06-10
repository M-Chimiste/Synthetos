"""Job queue SQLAlchemy model (Postgres-backed row-claim queue)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.core.types import JobStatus
from libs.storage.base import Base


class Job(Base):
    """A queued unit of work claimed by workers."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_claim", "status", "priority", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[JobStatus] = mapped_column(String(50), default=JobStatus.pending)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(nullable=True)
    # Structured failure detail: exc_type, error_class, traceback, attempt history.
    error_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    # Worker-death recoveries (stale-heartbeat reclaims). Distinct from
    # attempt_count, which counts operator failures.
    reclaim_count: Mapped[int] = mapped_column(Integer, default=0)
    # Failed attempts so far; the attempt now starting is attempt_count + 1.
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    # Retry backoff gate: claimable only once now >= not_before.
    not_before: Mapped[datetime | None] = mapped_column(nullable=True)
    # Set by the cancel API for in-flight jobs; the job supervisor polls it.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
