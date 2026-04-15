"""Tests for skill runtime trust enforcement."""

from __future__ import annotations

from libs.core.types import TrustTier
from libs.skills.enforcement import evaluate


def test_first_party_with_elevated_caps_allowed() -> None:
    out = evaluate(
        skill_id="x",
        trust_tier=TrustTier.first_party_trusted,
        manifest={"capabilities": ["fs.write", "network.access"]},
        cycle_config=None,
    )
    assert out.allowed is True
    assert out.elevated is True


def test_third_party_with_elevated_caps_blocked() -> None:
    out = evaluate(
        skill_id="x",
        trust_tier=TrustTier.third_party_untrusted,
        manifest={"capabilities": ["python.hooks"]},
        cycle_config=None,
    )
    assert out.allowed is False
    assert out.elevated is True


def test_user_local_with_elevated_caps_allowed() -> None:
    out = evaluate(
        skill_id="x",
        trust_tier=TrustTier.user_local_trusted,
        manifest={"capabilities": ["fs.write"]},
        cycle_config=None,
    )
    assert out.allowed is True


def test_first_party_required_blocks_user_local() -> None:
    out = evaluate(
        skill_id="x",
        trust_tier=TrustTier.user_local_trusted,
        manifest={"capabilities": []},
        cycle_config={"skills": {"require_first_party_for_execution": True}},
    )
    assert out.allowed is False
    assert "first_party_trusted" in out.reason


def test_first_party_required_allows_first_party() -> None:
    out = evaluate(
        skill_id="x",
        trust_tier=TrustTier.first_party_trusted,
        manifest={"capabilities": []},
        cycle_config={"skills": {"require_first_party_for_execution": True}},
    )
    assert out.allowed is True


def test_unknown_trust_tier_blocked() -> None:
    out = evaluate(
        skill_id="x",
        trust_tier="bogus",
        manifest={},
        cycle_config=None,
    )
    assert out.allowed is False


def test_no_capabilities_not_elevated() -> None:
    out = evaluate(
        skill_id="x",
        trust_tier=TrustTier.user_local_trusted,
        manifest={"capabilities": []},
        cycle_config=None,
    )
    assert out.elevated is False
    assert out.allowed is True
