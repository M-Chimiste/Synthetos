"""Tests for the pilot fixture contract loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from libs.pilot.fixture import (
    PilotFixtureError,
    list_fixtures,
    load_fixture,
)

FIXTURE_ROOT = Path("configs/problems")
SMOKE_FIXTURE = FIXTURE_ROOT / "ml_baseline_small"


def test_load_bundled_ci_safe_fixture() -> None:
    fixture = load_fixture(SMOKE_FIXTURE)
    assert fixture.problem_id == "ml_baseline_small"
    assert fixture.tier == "ci_safe"
    assert fixture.autonomy["mode"] == "supervised"
    assert fixture.autonomy["max_total_runs"] == 3
    assert fixture.seeds["global"] == 42
    assert fixture.readme.startswith("# ml_baseline_small")


def test_list_fixtures_includes_bundled() -> None:
    ids = list_fixtures(FIXTURE_ROOT)
    assert "ml_baseline_small" in ids
    assert "ml_sklearn_iris" in ids
    assert "ml_vision_tiny" in ids


def test_workstation_cpu_fixture_is_autonomous() -> None:
    fixture = load_fixture(FIXTURE_ROOT / "ml_sklearn_iris")
    assert fixture.tier == "workstation_cpu"
    assert fixture.autonomy["mode"] == "autonomous"


def test_workstation_gpu_fixture_requires_gpu() -> None:
    fixture = load_fixture(FIXTURE_ROOT / "ml_vision_tiny")
    assert fixture.tier == "workstation_gpu"
    assert fixture.autonomy["compute_cap"]["gpu"] is True


def test_missing_directory_errors(tmp_path: Path) -> None:
    with pytest.raises(PilotFixtureError):
        load_fixture(tmp_path / "nope")


def test_invalid_tier_rejected(tmp_path: Path) -> None:
    root = tmp_path / "bad"
    root.mkdir()
    (root / "charter.yaml").write_text(
        "title: t\n"
        "problem_statement: ps\n"
        "domain: d\n"
        "success_criteria: []\n"
        "expected_runtime_bucket: not_a_tier\n"
    )
    (root / "autonomy.yaml").write_text(
        "mode: supervised\nmax_total_runs: 1\nmax_wall_clock_hours: 0.1\n"
    )
    (root / "seeds.yaml").write_text("global: 1\n")
    (root / "README.md").write_text("x")
    with pytest.raises(PilotFixtureError, match="expected_runtime_bucket"):
        load_fixture(root)


def test_missing_seeds_rejected(tmp_path: Path) -> None:
    root = tmp_path / "bad"
    root.mkdir()
    (root / "charter.yaml").write_text(
        "title: t\n"
        "problem_statement: ps\n"
        "domain: d\n"
        "success_criteria: []\n"
        "expected_runtime_bucket: ci_safe\n"
    )
    (root / "autonomy.yaml").write_text(
        "mode: supervised\nmax_total_runs: 1\nmax_wall_clock_hours: 0.1\n"
    )
    (root / "README.md").write_text("x")
    with pytest.raises(PilotFixtureError):
        load_fixture(root)


def test_missing_compute_cap_rejected(tmp_path: Path) -> None:
    root = tmp_path / "bad"
    root.mkdir()
    (root / "charter.yaml").write_text(
        "title: t\n"
        "problem_statement: ps\n"
        "domain: d\n"
        "success_criteria: []\n"
        "expected_runtime_bucket: ci_safe\n"
    )
    (root / "autonomy.yaml").write_text(
        "mode: supervised\nmax_total_runs: 1\nmax_wall_clock_hours: 0.1\n"
    )
    (root / "seeds.yaml").write_text("global: 1\n")
    (root / "README.md").write_text("x")
    with pytest.raises(PilotFixtureError, match="compute_cap"):
        load_fixture(root)
