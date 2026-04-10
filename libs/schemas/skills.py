"""Pydantic schemas for skill packages."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from libs.core.types import TrustTier


class SkillManifest(BaseModel):
    """Validated skill manifest parsed from skill.md YAML frontmatter."""

    id: str
    version: str = "0.1.0"
    phase: str | None = None
    allowed_operators: list[str] = []
    preferred_models: list[str] = []
    context_inputs: list[str] = []
    outputs: list[str] = []
    capabilities: list[str] = []
    risk_level: str = "low"
    trust_tier_required: TrustTier = TrustTier.third_party_untrusted


class SkillDefinitionRead(BaseModel):
    """Schema for reading a persisted skill definition."""

    model_config = {"from_attributes": True}

    id: UUID
    skill_id: str
    version: str
    phase: str | None
    trust_tier: TrustTier
    manifest: dict[str, Any] | None
    content_hash: str | None
    enabled: bool
    source_path: str | None
    discovered_at: datetime
