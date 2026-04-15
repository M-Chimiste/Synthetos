"""Pydantic schemas for the Phase 6 patterns API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from libs.patterns.content_key import PATTERN_TYPES


class PatternSummary(BaseModel):
    """Compact pattern view for list endpoints."""

    id: UUID
    pattern_type: str
    title: str
    summary: str
    trust_tier: str
    evidence_count: int
    confidence: float
    staleness_score: float
    source_charter_ids: list[UUID]
    last_reinforced_at: datetime


class PatternObservationRead(BaseModel):
    id: UUID
    pattern_id: UUID
    charter_id: UUID
    cycle_id: UUID
    source_artifact_type: str
    source_artifact_id: UUID
    contribution: dict[str, Any] | None = None
    observed_at: datetime


class PatternDetail(PatternSummary):
    """Full pattern view with structured body and recent observations."""

    structured_body: dict[str, Any]
    consolidation_version: int
    first_observed_at: datetime
    last_observed_at: datetime
    created_at: datetime
    updated_at: datetime
    recent_observations: list[PatternObservationRead] = Field(default_factory=list)


class PatternList(BaseModel):
    items: list[PatternSummary]
    total: int
    offset: int = 0
    limit: int = 50


class ObservationList(BaseModel):
    items: list[PatternObservationRead]
    total: int
    offset: int = 0
    limit: int = 100


class PatternMatchRead(BaseModel):
    """Output of ``/retrieve-preview`` for debug/inspection."""

    pattern: PatternSummary
    similarity: float | None
    effective_confidence: float
    cross_charter: bool
    source_charter_ids: list[UUID]


class ConsolidateRequest(BaseModel):
    charter_id: UUID | None = None
    pattern_types: list[str] | None = None

    def validate_types(self) -> list[str] | None:
        if self.pattern_types is None:
            return None
        unknown = [t for t in self.pattern_types if t not in PATTERN_TYPES]
        if unknown:
            raise ValueError(f"unknown pattern_types: {unknown}")
        return self.pattern_types


class DecayRequest(BaseModel):
    force: bool = False
    max_staleness_days: int | None = None


class JobAcceptedResponse(BaseModel):
    job_id: UUID


class PatternApprovalRead(BaseModel):
    id: UUID
    pattern_id: UUID
    charter_id: UUID | None
    decision: str
    actor_type: str
    actor_id: str | None
    rationale: str
    expires_at: datetime | None
    created_at: datetime


class ApproveRequest(BaseModel):
    rationale: str = Field(min_length=1)
    charter_id: UUID | None = None
    expires_at: datetime | None = None


class RejectRequest(BaseModel):
    rationale: str = Field(min_length=1)
    charter_id: UUID | None = None


class TrustTierUpdateRequest(BaseModel):
    trust_tier: str
    rationale: str = Field(min_length=1)


class RetrievePreviewRequest(BaseModel):
    charter_id: UUID
    current_cycle_id: UUID | None = None
    problem_profile_embedding: list[float] | None = None
    pattern_types: list[str] | None = None
    min_confidence: float = 0.0
    max_staleness_days: int = 90
    cross_charter_only: bool = False
    limit: int = Field(default=10, ge=1, le=100)
