"""Parse skill.md files into manifest + body."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from libs.schemas.skills import SkillManifest


class SkillParseError(Exception):
    """Raised when a skill.md file cannot be parsed."""


def parse_skill_file(path: Path) -> tuple[SkillManifest, str]:
    """Parse a skill.md file into a validated manifest and markdown body.

    Returns (manifest, body) tuple.
    Raises SkillParseError if the file cannot be parsed or validated.
    """
    try:
        post = frontmatter.load(str(path))
    except Exception as e:
        raise SkillParseError(f"Failed to parse {path}: {e}") from e

    metadata = dict(post.metadata)
    if "id" not in metadata:
        raise SkillParseError(f"Skill at {path} missing required 'id' in frontmatter")

    try:
        manifest = SkillManifest(**metadata)
    except Exception as e:
        raise SkillParseError(f"Invalid manifest in {path}: {e}") from e

    return manifest, post.content
