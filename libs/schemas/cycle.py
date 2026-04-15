"""Pydantic schemas for ResearchCycle CRUD operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from libs.core.types import CycleStatus


class CycleCreate(BaseModel):
    """Schema for creating a new research cycle."""

    charter_id: UUID
    config: dict[str, Any] | None = None


class CycleRead(BaseModel):
    """Schema for reading a cycle."""

    model_config = {"from_attributes": True}

    id: UUID
    charter_id: UUID
    status: CycleStatus
    config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class CycleTransition(BaseModel):
    """Schema for requesting a state transition."""

    target_status: CycleStatus
