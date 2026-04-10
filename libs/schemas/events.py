"""Pydantic schemas for domain events."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from libs.core.types import ActorType


class EventRead(BaseModel):
    """Schema for reading a domain event."""

    model_config = {"from_attributes": True}

    id: UUID
    charter_id: UUID | None
    cycle_id: UUID | None
    event_type: str
    payload: dict[str, Any] | None
    actor_type: ActorType
    actor_id: str | None
    created_at: datetime


class EventFilter(BaseModel):
    """Filter parameters for querying events."""

    charter_id: UUID | None = None
    cycle_id: UUID | None = None
    event_type: str | None = None
    after_id: UUID | None = None
