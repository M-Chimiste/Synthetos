"""Pydantic schemas for paper cards."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class PaperCardRead(BaseModel):
    """Schema for reading a paper card."""

    model_config = {"from_attributes": True}

    id: UUID
    session_id: UUID
    charter_id: UUID
    source: str
    external_id: str
    dedupe_key: str
    title: str
    abstract: str
    authors: list[str] | None
    categories: list[str] | None
    venue: str | None
    year: int | None
    published_at: datetime | None
    doi: str | None
    source_url: str | None
    pdf_url: str | None
    bm25_score: float | None
    dense_score: float | None
    first_stage_score: float | None
    rerank_score: float | None
    final_score: float | None
    view_membership: list[str] | None
    triage_status: str
    triage_reason: str | None
    metadata_analysis: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
