"""Tests for skill manifest validation, loader strict mode, and dependency checks."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from libs.skills.dependencies import validate_skill_dependencies
from libs.skills.loader import SkillValidationError, load_all_skills, parse_skill_file
from libs.skills.manifest import (
    LoadedSkill,
    SkillManifest,
    ValidationIssue,
)

# ---------------------------------------------------------------------------
# SkillManifest.validate_against_registry
# ---------------------------------------------------------------------------


class TestManifestValidation:
    def test_valid_manifest_no_issues(self) -> None:
        manifest = SkillManifest(
            id="literature.test_skill",
            version="1.0.0",
            phase="literature",
            allowed_operators=["initialize_cycle"],
            outputs=["result"],
            capabilities=["read"],
            risk_level="low",
        )
        issues = manifest.validate_against_registry()
        assert issues == []

    def test_invalid_semver(self) -> None:
        manifest = SkillManifest(
            id="test.skill",
            version="bad",
            phase="literature",
            allowed_operators=["initialize_cycle"],
            outputs=[],
            capabilities=[],
            risk_level="low",
        )
        issues = manifest.validate_against_registry()
        assert any(i.code == "invalid_version" and i.severity == "error" for i in issues)

    def test_unknown_phase(self) -> None:
        manifest = SkillManifest(
            id="test.skill",
            version="1.0.0",
            phase="nonexistent",
            allowed_operators=["initialize_cycle"],
            outputs=[],
            capabilities=[],
            risk_level="low",
        )
        issues = manifest.validate_against_registry()
        assert any(i.code == "unknown_phase" and i.severity == "warning" for i in issues)

    def test_unknown_operators(self) -> None:
        manifest = SkillManifest(
            id="test.skill",
            version="1.0.0",
            phase="literature",
            allowed_operators=["initialize_cycle", "nonexistent_op"],
            outputs=[],
            capabilities=[],
            risk_level="low",
        )
        issues = manifest.validate_against_registry()
        assert any(i.code == "unknown_operators" for i in issues)

    def test_empty_operators(self) -> None:
        manifest = SkillManifest(
            id="test.skill",
            version="1.0.0",
            phase="literature",
            allowed_operators=[],
            outputs=[],
            capabilities=[],
            risk_level="low",
        )
        issues = manifest.validate_against_registry()
        assert any(i.code == "empty_operators" and i.severity == "error" for i in issues)

    def test_empty_id(self) -> None:
        manifest = SkillManifest(
            id="",
            version="1.0.0",
            phase="literature",
            allowed_operators=["initialize_cycle"],
            outputs=[],
            capabilities=[],
            risk_level="low",
        )
        issues = manifest.validate_against_registry()
        assert any(i.code == "empty_id" and i.severity == "error" for i in issues)

    def test_custom_operator_registry(self) -> None:
        manifest = SkillManifest(
            id="test.skill",
            version="1.0.0",
            phase="literature",
            allowed_operators=["custom_op"],
            outputs=[],
            capabilities=[],
            risk_level="low",
        )
        issues = manifest.validate_against_registry(operator_names={"custom_op"})
        assert not any(i.code == "unknown_operators" for i in issues)

    def test_requires_and_conflicts_fields(self) -> None:
        manifest = SkillManifest(
            id="test.skill",
            version="1.0.0",
            phase="literature",
            allowed_operators=["initialize_cycle"],
            outputs=[],
            capabilities=[],
            risk_level="low",
            requires=["other.skill"],
            conflicts_with=["bad.skill"],
        )
        assert manifest.requires == ["other.skill"]
        assert manifest.conflicts_with == ["bad.skill"]


# ---------------------------------------------------------------------------
# ValidationIssue model
# ---------------------------------------------------------------------------


def test_validation_issue_serialization() -> None:
    issue = ValidationIssue(
        severity="error",
        code="test_code",
        message="test message",
        field="test_field",
    )
    data = issue.model_dump()
    assert data["severity"] == "error"
    assert data["code"] == "test_code"
    assert data["field"] == "test_field"


# ---------------------------------------------------------------------------
# parse_skill_file with validation
# ---------------------------------------------------------------------------


class TestParseSkillFileValidation:
    def test_valid_skill_file(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.md").write_text(textwrap.dedent("""\
            ---
            id: test.my_skill
            version: 1.0.0
            phase: literature
            allowed_operators:
              - initialize_cycle
            outputs:
              - result
            capabilities:
              - read
            risk_level: low
            ---

            # My Skill
        """))
        skill = parse_skill_file(skill_dir / "skill.md")
        assert skill.is_valid is True
        assert skill.validation_issues == []

    def test_invalid_version_produces_issues(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad_ver"
        skill_dir.mkdir()
        (skill_dir / "skill.md").write_text(textwrap.dedent("""\
            ---
            id: test.bad_ver
            version: not-a-version
            phase: literature
            allowed_operators:
              - initialize_cycle
            outputs: []
            capabilities: []
            risk_level: low
            ---

            # Bad Version
        """))
        skill = parse_skill_file(skill_dir / "skill.md")
        assert skill.is_valid is False
        assert any(i.get("code") == "invalid_version" for i in skill.validation_issues)

    def test_unknown_hook_exports_produce_warnings(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "hook_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.md").write_text(textwrap.dedent("""\
            ---
            id: test.hook_skill
            version: 1.0.0
            phase: literature
            allowed_operators:
              - initialize_cycle
            outputs: []
            capabilities: []
            risk_level: low
            ---

            # Hook Skill
        """))
        (skill_dir / "hooks.py").write_text("def unexpected_hook(): pass\n")
        skill = parse_skill_file(skill_dir / "skill.md")
        assert any(i.get("code") == "unknown_hooks" for i in skill.validation_issues)


# ---------------------------------------------------------------------------
# load_all_skills strict mode
# ---------------------------------------------------------------------------


class TestLoadAllSkillsStrict:
    def _write_skill(self, skill_dir: Path, *, version: str = "1.0.0") -> None:
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "skill.md").write_text(textwrap.dedent(f"""\
            ---
            id: test.{skill_dir.name}
            version: {version}
            phase: literature
            allowed_operators:
              - initialize_cycle
            outputs: []
            capabilities: []
            risk_level: low
            ---

            # {skill_dir.name}
        """))

    def test_lenient_mode_includes_invalid(self, tmp_path: Path) -> None:
        self._write_skill(tmp_path / "skills" / "good_skill")
        self._write_skill(tmp_path / "skills" / "bad_skill", version="BAD")
        skills = load_all_skills([tmp_path / "skills"], strict=False)
        assert len(skills) == 2
        assert any(not s.is_valid for s in skills)

    def test_strict_mode_raises_on_invalid(self, tmp_path: Path) -> None:
        self._write_skill(tmp_path / "skills" / "good_skill")
        self._write_skill(tmp_path / "skills" / "bad_skill", version="BAD")
        with pytest.raises(SkillValidationError, match="bad_skill"):
            load_all_skills([tmp_path / "skills"], strict=True)

    def test_strict_mode_all_valid(self, tmp_path: Path) -> None:
        self._write_skill(tmp_path / "skills" / "skill_a")
        self._write_skill(tmp_path / "skills" / "skill_b")
        skills = load_all_skills([tmp_path / "skills"], strict=True)
        assert len(skills) == 2
        assert all(s.is_valid for s in skills)


# ---------------------------------------------------------------------------
# Skill dependency validation
# ---------------------------------------------------------------------------


class TestSkillDependencies:
    def _make_skill(self, key: str, *, requires: list[str] | None = None,
                    conflicts_with: list[str] | None = None) -> LoadedSkill:
        return LoadedSkill(
            path=Path(f"/tmp/{key}"),
            skill_key=key,
            version="1.0.0",
            phase="literature",
            manifest=SkillManifest(
                id=key,
                version="1.0.0",
                phase="literature",
                allowed_operators=["initialize_cycle"],
                outputs=[],
                capabilities=[],
                risk_level="low",
                requires=requires or [],
                conflicts_with=conflicts_with or [],
            ),
            body_markdown="",
            content_hash="abc",
        )

    def test_no_deps_no_issues(self) -> None:
        skills = [self._make_skill("a"), self._make_skill("b")]
        result = validate_skill_dependencies(skills)
        assert all(issues == [] for issues in result.values())

    def test_missing_dependency(self) -> None:
        skills = [self._make_skill("a", requires=["missing.skill"])]
        result = validate_skill_dependencies(skills)
        assert any(i.code == "missing_dependency" for i in result["a"])

    def test_satisfied_dependency(self) -> None:
        skills = [
            self._make_skill("a", requires=["b"]),
            self._make_skill("b"),
        ]
        result = validate_skill_dependencies(skills)
        assert result["a"] == []

    def test_conflict_detected(self) -> None:
        skills = [
            self._make_skill("a", conflicts_with=["b"]),
            self._make_skill("b"),
        ]
        result = validate_skill_dependencies(skills)
        assert any(i.code == "conflict_detected" for i in result["a"])

    def test_conflict_not_active_is_ok(self) -> None:
        inactive = self._make_skill("b")
        inactive.is_valid = False
        skills = [
            self._make_skill("a", conflicts_with=["b"]),
            inactive,
        ]
        result = validate_skill_dependencies(skills)
        assert result["a"] == []


# ---------------------------------------------------------------------------
# First-party skills pass validation
# ---------------------------------------------------------------------------


def test_all_first_party_skills_are_valid() -> None:
    skills_root = Path("skills")
    if not skills_root.exists():
        pytest.skip("skills/ directory not found")
    skills = load_all_skills([skills_root])
    for skill in skills:
        assert skill.is_valid, f"{skill.skill_key}: {skill.validation_issues}"
