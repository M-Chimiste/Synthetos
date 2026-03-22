from pathlib import Path

from libs.skills.loader import discover_hook_exports, parse_skill_file


def test_parse_skill_file() -> None:
    skill = parse_skill_file(
        Path("/Users/c/software_projects/Synthetos/skills/literature/problem_scoping_support/skill.md")
    )
    assert skill.is_valid is True
    assert skill.manifest.id == "literature.problem_scoping_support"


def test_discover_hook_exports() -> None:
    exports = discover_hook_exports(
        Path("/Users/c/software_projects/Synthetos/skills/literature/problem_scoping_support/hooks.py")
    )
    assert exports == ["shape_context"]

