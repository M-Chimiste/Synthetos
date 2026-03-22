from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    id: str
    version: str
    phase: str
    allowed_operators: list[str]
    outputs: list[str]
    capabilities: list[str]
    risk_level: Literal["low", "medium", "high"]


class LoadedSkill(BaseModel):
    path: Path
    skill_key: str
    version: str
    phase: str
    manifest: SkillManifest
    body_markdown: str
    content_hash: str
    hooks_path: Path | None = None
    hook_exports: list[str] = Field(default_factory=list)
    is_valid: bool = True
    validation_issues: list[dict[str, str | dict]] = Field(default_factory=list)
