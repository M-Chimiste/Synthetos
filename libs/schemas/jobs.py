"""Pydantic schemas for jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from libs.core.types import JobStatus


class JobRead(BaseModel):
    """Schema for reading a job."""

    model_config = {"from_attributes": True}

    id: UUID
    cycle_id: UUID | None
    job_type: str
    status: JobStatus
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    error: str | None
    claimed_by: str | None
    priority: int
    created_at: datetime
    completed_at: datetime | None


class JobCreate(BaseModel):
    """Schema for creating a job (internal use)."""

    cycle_id: UUID | None = None
    job_type: str
    payload: dict[str, Any] | None = None
    priority: int = 0
