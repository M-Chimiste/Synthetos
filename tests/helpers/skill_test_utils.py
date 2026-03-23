"""Helpers for testing custom skills."""

from __future__ import annotations

from pathlib import Path

from libs.skills.loader import parse_skill_file
from libs.skills.manifest import LoadedSkill


def load_and_validate_skill(skill_path: Path) -> LoadedSkill:
    """Load a skill file and return the LoadedSkill with validation results.

    Raises AssertionError if the skill is not valid.
    """
    skill = parse_skill_file(skill_path)
    assert skill.is_valid, (
        f"Skill '{skill.skill_key}' failed validation: {skill.validation_issues}"
    )
    return skill


def assert_skill_binds_to(skill: LoadedSkill, operator: str) -> None:
    """Assert that a skill declares the given operator in allowed_operators."""
    assert operator in skill.manifest.allowed_operators, (
        f"Skill '{skill.skill_key}' does not bind to operator '{operator}'. "
        f"Allowed: {skill.manifest.allowed_operators}"
    )
