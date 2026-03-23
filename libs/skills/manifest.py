from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

KNOWN_PHASES = {
    "planning", "literature", "ideation", "coding",
    "execution", "verification", "reporting",
}

KNOWN_OPERATORS = {
    "initialize_cycle",
    "source_retrieval",
    "literature_screen",
    "shortlist_rank",
    "fulltext_escalation",
    "literature_report",
    "evidence_extraction",
    "hypothesis_generation",
    "hypothesis_critique",
    "protocol_compilation",
    "run_prepare",
    "run_execute",
    "run_finalize",
    "run_retry_repair",
    "run_verify",
    "failure_postmortem",
    "verification_report",
}

KNOWN_HOOK_NAMES = {"pre_operator", "post_operator", "on_failure", "shape_context"}

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    field: str | None = None


class SkillManifest(BaseModel):
    id: str
    version: str
    phase: str
    allowed_operators: list[str]
    outputs: list[str]
    capabilities: list[str]
    risk_level: Literal["low", "medium", "high"]
    requires: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)

    def validate_against_registry(
        self,
        operator_names: set[str] | None = None,
    ) -> list[ValidationIssue]:
        operators = operator_names if operator_names is not None else KNOWN_OPERATORS
        issues: list[ValidationIssue] = []

        if not _SEMVER_RE.match(self.version):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_version",
                    message=f"Version '{self.version}' is not valid semver (expected X.Y.Z)",
                    field="version",
                )
            )

        if self.phase not in KNOWN_PHASES:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="unknown_phase",
                    message=f"Phase '{self.phase}' is not in known phases: {sorted(KNOWN_PHASES)}",
                    field="phase",
                )
            )

        unknown_ops = set(self.allowed_operators) - operators
        if unknown_ops:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="unknown_operators",
                    message=f"Operators not in registry: {sorted(unknown_ops)}",
                    field="allowed_operators",
                )
            )

        if not self.allowed_operators:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="empty_operators",
                    message="Skill must declare at least one allowed operator",
                    field="allowed_operators",
                )
            )

        if not self.id:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="empty_id",
                    message="Skill id must not be empty",
                    field="id",
                )
            )

        return issues


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
