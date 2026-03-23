"""Skill dependency and conflict validation."""

from __future__ import annotations

from libs.skills.manifest import LoadedSkill, ValidationIssue


def validate_skill_dependencies(skills: list[LoadedSkill]) -> dict[str, list[ValidationIssue]]:
    """Check that all skill `requires` are satisfied and `conflicts_with` are not active.

    Returns a mapping from skill_key to its dependency issues (empty list if clean).
    """
    active_keys = {s.skill_key for s in skills if s.is_valid}
    results: dict[str, list[ValidationIssue]] = {}

    for skill in skills:
        if not skill.is_valid:
            continue
        issues: list[ValidationIssue] = []
        manifest = skill.manifest

        missing = set(manifest.requires) - active_keys
        if missing:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_dependency",
                    message=f"Required skills not found or inactive: {sorted(missing)}",
                    field="requires",
                )
            )

        conflicts = set(manifest.conflicts_with) & active_keys
        if conflicts:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="conflict_detected",
                    message=f"Conflicting skills are active: {sorted(conflicts)}",
                    field="conflicts_with",
                )
            )

        results[skill.skill_key] = issues

    return results
