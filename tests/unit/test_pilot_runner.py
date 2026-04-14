"""Tests for the pilot runner's cycle config builder.

Here we test the pure config-shaping helpers in isolation. The end-to-end
kickoff path is covered in ``tests/integration/test_phase6_pilot.py``.
"""

from __future__ import annotations

from pathlib import Path

from libs.pilot.fixture import load_fixture
from libs.pilot.runner import _cycle_config, _discovery_profile

FIXTURE_ROOT = Path("configs/problems")


def test_cycle_config_includes_autonomy_seeds_and_pilot_block() -> None:
    fixture = load_fixture(FIXTURE_ROOT / "ml_baseline_small")
    cfg = _cycle_config(fixture)
    assert cfg["autonomy"]["mode"] == "supervised"
    assert cfg["autonomy"]["max_total_runs"] == 3
    assert cfg["seeds"]["global"] == 42
    pilot = cfg["pilot"]
    assert pilot["problem_id"] == "ml_baseline_small"
    assert pilot["tier"] == "ci_safe"
    assert isinstance(pilot["success_criteria"], list)


def test_cycle_config_carries_expected_block_for_evaluation() -> None:
    fixture = load_fixture(FIXTURE_ROOT / "ml_sklearn_iris")
    cfg = _cycle_config(fixture)
    assert "expected" in cfg["pilot"]
    assert cfg["pilot"]["expected"]["pattern_reuse"]["expect_successful_line"] is True


def test_discovery_profile_uses_problem_statement_and_domain_hints() -> None:
    fixture = load_fixture(FIXTURE_ROOT / "ml_baseline_small")
    profile = _discovery_profile(fixture)
    assert "linearly separable toy dataset" in profile.query_text
    assert profile.source_scope is not None
    assert profile.source_scope["domain"] == "synthetic-classification"
    assert profile.source_scope["search_hints"]["synonyms"] == ["synthetic-classification"]
