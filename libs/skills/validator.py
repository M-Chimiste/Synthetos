"""Validate skill packages for structure and trust tier compliance."""

from __future__ import annotations

from pathlib import Path

from libs.core.types import TrustTier
from libs.schemas.skills import SkillManifest


class SkillValidationError(Exception):
    """Raised when a skill fails validation."""


# Capabilities that require elevated trust
ELEVATED_CAPABILITIES = {
    "python.hooks",
    "fs.write",
    "network.access",
    "run.control",
}


def validate_skill(
    manifest: SkillManifest,
    source_path: Path,
    trust_tier: TrustTier,
) -> list[str]:
    """Validate a skill manifest against its trust tier.

    Returns a list of validation warnings (empty if clean).
    Raises SkillValidationError for blocking issues.
    """
    warnings: list[str] = []

    # Check if capabilities require higher trust
    for cap in manifest.capabilities:
        if cap in ELEVATED_CAPABILITIES and trust_tier == TrustTier.third_party_untrusted:
            raise SkillValidationError(
                f"Skill '{manifest.id}' requires capability '{cap}' "
                f"but has trust tier '{trust_tier.value}'. "
                "Elevate to user_local_trusted or first_party_trusted."
            )

    # Check hooks.py exists if capabilities suggest it
    if "python.hooks" in manifest.capabilities:
        hooks_path = source_path.parent / "hooks.py"
        if not hooks_path.exists():
            warnings.append(
                f"Skill '{manifest.id}' declares python.hooks capability "
                "but hooks.py not found"
            )

    # Warn about missing version
    if manifest.version == "0.1.0":
        warnings.append(f"Skill '{manifest.id}' uses default version 0.1.0")

    return warnings
