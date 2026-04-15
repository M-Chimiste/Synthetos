"""Pydantic schema for the assembled ResearchState snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from libs.core.types import CharterStatus, CycleStatus


class CycleSummary(BaseModel):
    """Brief summary of a cycle within a state snapshot."""

    id: UUID
    status: CycleStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ResearchStateSnapshot(BaseModel):
    """Read-only aggregate view of all state for a charter.

    This is NOT a database model. It is assembled by querying
    related tables and composing a single response.
    """

    charter_id: UUID
    charter_title: str
    charter_status: CharterStatus
    cycles: list[CycleSummary]
    active_cycle: CycleSummary | None
    total_events: int
    total_jobs: int
    recent_events: list[dict[str, Any]]
