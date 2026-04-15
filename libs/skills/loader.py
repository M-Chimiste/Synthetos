"""Discover skill.md packages from configured directories."""

from __future__ import annotations

import hashlib
from pathlib import Path

from libs.core.logging import get_logger
from libs.core.types import TrustTier
from libs.schemas.skills import SkillManifest
from libs.skills.parser import SkillParseError, parse_skill_file
from libs.skills.validator import SkillValidationError, validate_skill

log = get_logger(__name__)


class DiscoveredSkill:
    """A skill found on disk, parsed and validated."""

    def __init__(
        self,
        manifest: SkillManifest,
        body: str,
        source_path: Path,
        trust_tier: TrustTier,
        content_hash: str,
        warnings: list[str],
    ) -> None:
        self.manifest = manifest
        self.body = body
        self.source_path = source_path
        self.trust_tier = trust_tier
        self.content_hash = content_hash
        self.warnings = warnings


def _compute_hash(path: Path) -> str:
    """Compute SHA-256 hash of a skill.md file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _infer_trust_tier(path: Path, first_party_root: Path | None = None) -> TrustTier:
    """Infer trust tier from file location."""
    if first_party_root and path.is_relative_to(first_party_root):
        return TrustTier.first_party_trusted
    return TrustTier.user_local_trusted


def discover_skills(
    search_paths: list[Path],
    *,
    first_party_root: Path | None = None,
) -> list[DiscoveredSkill]:
    """Walk search paths and discover all valid skill.md packages.

    Args:
        search_paths: Directories to search for skill.md files.
        first_party_root: Path prefix that marks skills as first-party trusted.

    Returns:
        List of discovered and validated skills.
    """
    discovered: list[DiscoveredSkill] = []

    for search_path in search_paths:
        if not search_path.exists():
            log.warning("skill_path_not_found", path=str(search_path))
            continue

        for skill_md in search_path.rglob("skill.md"):
            try:
                manifest, body = parse_skill_file(skill_md)
            except SkillParseError as e:
                log.warning("skill_parse_failed", path=str(skill_md), error=str(e))
                continue

            trust_tier = _infer_trust_tier(skill_md, first_party_root)

            try:
                warnings = validate_skill(manifest, skill_md, trust_tier)
            except SkillValidationError as e:
                log.warning("skill_validation_failed", skill_id=manifest.id, error=str(e))
                continue

            content_hash = _compute_hash(skill_md)

            discovered.append(
                DiscoveredSkill(
                    manifest=manifest,
                    body=body,
                    source_path=skill_md,
                    trust_tier=trust_tier,
                    content_hash=content_hash,
                    warnings=warnings,
                )
            )
            log.info(
                "skill_discovered",
                skill_id=manifest.id,
                trust_tier=trust_tier.value,
                warnings=warnings,
            )

    return discovered
