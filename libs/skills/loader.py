from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable
from pathlib import Path

import yaml

from libs.skills.manifest import (
    KNOWN_HOOK_NAMES,
    LoadedSkill,
    SkillManifest,
    ValidationIssue,
)


def parse_skill_file(path: Path) -> LoadedSkill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return LoadedSkill(
            path=path,
            skill_key=path.parent.name,
            version="0.0.0",
            phase="unknown",
            manifest=SkillManifest(
                id=f"invalid.{path.parent.name}",
                version="0.0.0",
                phase="unknown",
                allowed_operators=[],
                outputs=[],
                capabilities=[],
                risk_level="low",
            ),
            body_markdown=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            is_valid=False,
            validation_issues=[{"severity": "error", "message": "Missing YAML frontmatter"}],
        )
    _, rest = text.split("---\n", 1)
    raw_frontmatter, body = rest.split("\n---\n", 1)
    data = yaml.safe_load(raw_frontmatter) or {}
    manifest = SkillManifest.model_validate(data)
    hooks_path = path.parent / "hooks.py"
    hook_exports = discover_hook_exports(hooks_path) if hooks_path.exists() else []

    # Run manifest validation
    registry_issues = manifest.validate_against_registry()
    hook_issues = _validate_hook_exports(hook_exports)
    all_issues = registry_issues + hook_issues

    has_errors = any(issue.severity == "error" for issue in all_issues)
    serialized_issues = [issue.model_dump() for issue in all_issues]

    return LoadedSkill(
        path=path.parent,
        skill_key=manifest.id,
        version=manifest.version,
        phase=manifest.phase,
        manifest=manifest,
        body_markdown=body.strip(),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        hooks_path=hooks_path if hooks_path.exists() else None,
        hook_exports=hook_exports,
        is_valid=not has_errors,
        validation_issues=serialized_issues,
    )


def _validate_hook_exports(hook_exports: list[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    unknown = set(hook_exports) - KNOWN_HOOK_NAMES
    if unknown:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="unknown_hooks",
                message=f"Hook exports not in known set: {sorted(unknown)}. "
                f"Known hooks: {sorted(KNOWN_HOOK_NAMES)}",
                field="hook_exports",
            )
        )
    return issues


def discover_hook_exports(path: Path) -> list[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    exports: list[str] = []
    for node in module.body:
        if isinstance(node, ast.FunctionDef):
            exports.append(node.name)
    return exports


def load_all_skills(paths: Iterable[Path], *, strict: bool = False) -> list[LoadedSkill]:
    loaded: list[LoadedSkill] = []
    for root in paths:
        if not root.exists():
            continue
        for skill_file in sorted(root.rglob("skill.md")):
            try:
                skill = parse_skill_file(skill_file)
                if strict and not skill.is_valid:
                    error_messages = [
                        issue.get("message", "unknown")
                        for issue in skill.validation_issues
                        if issue.get("severity") == "error"
                    ]
                    raise SkillValidationError(
                        f"Skill '{skill.skill_key}' failed strict validation: "
                        + "; ".join(error_messages)
                    )
                loaded.append(skill)
            except SkillValidationError:
                raise
            except Exception as exc:
                loaded.append(
                    LoadedSkill(
                        path=skill_file.parent,
                        skill_key=skill_file.parent.name,
                        version="0.0.0",
                        phase="unknown",
                        manifest=SkillManifest(
                            id=f"invalid.{skill_file.parent.name}",
                            version="0.0.0",
                            phase="unknown",
                            allowed_operators=[],
                            outputs=[],
                            capabilities=[],
                            risk_level="low",
                        ),
                        body_markdown="",
                        content_hash="",
                        is_valid=False,
                        validation_issues=[{"severity": "error", "message": str(exc)}],
                    )
                )
    return loaded


class SkillValidationError(Exception):
    pass
