"""Integration test: load all first-party skills with strict validation and sync to DB."""

from __future__ import annotations

from pathlib import Path

import pytest

from libs.skills.dependencies import validate_skill_dependencies
from libs.skills.loader import load_all_skills

SKILLS_ROOT = Path("skills")


def test_all_first_party_skills_load_strict() -> None:
    """All skills in the skills/ directory pass strict validation."""
    if not SKILLS_ROOT.exists():
        pytest.skip("skills/ directory not found")
    skills = load_all_skills([SKILLS_ROOT], strict=True)
    assert len(skills) >= 13, f"Expected at least 13 skills, found {len(skills)}"
    for skill in skills:
        assert skill.is_valid, f"{skill.skill_key}: {skill.validation_issues}"


def test_no_dependency_conflicts() -> None:
    """No first-party skills have unsatisfied dependencies or active conflicts."""
    if not SKILLS_ROOT.exists():
        pytest.skip("skills/ directory not found")
    skills = load_all_skills([SKILLS_ROOT])
    dep_results = validate_skill_dependencies(skills)
    for skill_key, issues in dep_results.items():
        assert not issues, f"Skill '{skill_key}' has dependency issues: {issues}"


def test_skills_cover_all_phases() -> None:
    """First-party skills cover the expected phases."""
    if not SKILLS_ROOT.exists():
        pytest.skip("skills/ directory not found")
    skills = load_all_skills([SKILLS_ROOT])
    phases = {s.phase for s in skills if s.is_valid}
    # We should have skills for at least these phases
    expected = {"planning", "literature", "ideation", "coding", "verification"}
    covered = phases & expected
    assert len(covered) >= 4, f"Expected coverage of 4+ phases, got: {covered}"


def test_example_skills_are_valid() -> None:
    """Example skills in skills/examples/ pass validation."""
    examples_root = SKILLS_ROOT / "examples"
    if not examples_root.exists():
        pytest.skip("skills/examples/ directory not found")
    skills = load_all_skills([examples_root])
    assert len(skills) >= 2, f"Expected at least 2 example skills, found {len(skills)}"
    for skill in skills:
        assert skill.is_valid, f"Example skill '{skill.skill_key}': {skill.validation_issues}"
