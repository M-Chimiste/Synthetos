"""Skill runtime trust enforcement.

Validator (``libs/skills/validator.py``) only runs at discovery time. At
runtime, every operator that binds a skill calls
``libs/skills/lineage.record_skill_usage`` -- the real enforcement boundary.

This module provides a pure ``evaluate`` function that decides whether an
operator may bind a given skill under the active cycle policy, plus a typed
``SkillTrustViolation`` exception for callers. ``lineage.record_skill_usage``
is a thin wrapper around ``evaluate``.

Policy knobs (read from ``ResearchCycle.config``):
  * ``skills.require_first_party_for_execution``: if True, only
    first_party_trusted skills may be bound regardless of capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from libs.core.types import TrustTier
from libs.skills.validator import ELEVATED_CAPABILITIES


class SkillTrustViolation(Exception):
    """Raised when runtime trust policy blocks a skill binding."""

    def __init__(self, *, skill_id: str, reason: str):
        super().__init__(f"Skill '{skill_id}' blocked: {reason}")
        self.skill_id = skill_id
        self.reason = reason


@dataclass(frozen=True)
class EnforcementResult:
    allowed: bool
    reason: str
    elevated: bool


def _capabilities(manifest: dict[str, Any] | None) -> list[str]:
    if not manifest:
        return []
    caps = manifest.get("capabilities") or []
    return [str(c) for c in caps]


def evaluate(
    *,
    skill_id: str,
    trust_tier: TrustTier | str,
    manifest: dict[str, Any] | None,
    cycle_config: dict[str, Any] | None,
) -> EnforcementResult:
    """Return whether this skill may be bound under the given cycle policy.

    Elevated capabilities (``python.hooks``, ``fs.write``, ``network.access``,
    ``run.control``) require at least ``user_local_trusted``.
    If ``skills.require_first_party_for_execution`` is True, only
    ``first_party_trusted`` is allowed regardless of capabilities.
    """
    if isinstance(trust_tier, str):
        try:
            trust_tier = TrustTier(trust_tier)
        except ValueError:
            return EnforcementResult(
                allowed=False,
                reason=f"unknown trust tier '{trust_tier}'",
                elevated=False,
            )

    caps = _capabilities(manifest)
    elevated = any(c in ELEVATED_CAPABILITIES for c in caps)

    cfg = (cycle_config or {}).get("skills", {})
    require_first_party = bool(cfg.get("require_first_party_for_execution", False))
    if require_first_party and trust_tier != TrustTier.first_party_trusted:
        return EnforcementResult(
            allowed=False,
            reason=(
                "cycle policy requires first_party_trusted skills but "
                f"'{skill_id}' has trust tier '{trust_tier.value}'"
            ),
            elevated=elevated,
        )

    if elevated and trust_tier == TrustTier.third_party_untrusted:
        return EnforcementResult(
            allowed=False,
            reason=(
                f"skill declares elevated capabilities {sorted(set(caps) & ELEVATED_CAPABILITIES)} "
                "but trust tier is third_party_untrusted"
            ),
            elevated=True,
        )

    return EnforcementResult(allowed=True, reason="", elevated=elevated)
