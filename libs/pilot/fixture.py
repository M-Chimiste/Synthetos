"""Pilot fixture loader and contract validator.

A pilot fixture lives in ``configs/problems/<problem_id>/`` and is a small,
seeded research problem used to exercise the full Synthetos chain end-to-end
(discovery -> analysis -> ideation -> protocol -> execution -> verification ->
loop -> report -> consolidation). Fixtures fall into one of three runtime
buckets:

  * ``ci_safe`` -- CPU-only, <5 min, no network, runnable on every CI build.
  * ``workstation_cpu`` -- CPU-only, <30 min, run locally or on nightly CI.
  * ``workstation_gpu`` -- GPU-required, run by the researcher.

This module *only* validates and loads fixtures. The runner that consumes
them lives in ``libs.pilot.runner``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VALID_TIERS = {"ci_safe", "workstation_cpu", "workstation_gpu"}


class PilotFixtureError(ValueError):
    """Raised when a pilot fixture fails contract validation."""


@dataclass
class PilotFixture:
    problem_id: str
    root: Path
    charter: dict[str, Any]
    autonomy: dict[str, Any]
    seeds: dict[str, Any]
    expected: dict[str, Any] = field(default_factory=dict)
    readme: str = ""

    @property
    def tier(self) -> str:
        return str(self.charter.get("expected_runtime_bucket", ""))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PilotFixtureError(f"required fixture file missing: {path}")
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise PilotFixtureError(f"{path} must be a YAML mapping at top level")
    return data


def _require_keys(payload: dict[str, Any], keys: list[str], path: Path) -> None:
    missing = [k for k in keys if k not in payload]
    if missing:
        raise PilotFixtureError(
            f"{path} is missing required keys: {sorted(missing)}"
        )


def load_fixture(root: Path) -> PilotFixture:
    """Load and validate a fixture directory.

    Raises ``PilotFixtureError`` if the contract is violated.
    """
    if not root.is_dir():
        raise PilotFixtureError(f"fixture directory not found: {root}")

    charter = _load_yaml(root / "charter.yaml")
    _require_keys(
        charter,
        ["title", "problem_statement", "domain", "success_criteria", "expected_runtime_bucket"],
        root / "charter.yaml",
    )
    tier = charter["expected_runtime_bucket"]
    if tier not in VALID_TIERS:
        raise PilotFixtureError(
            f"expected_runtime_bucket must be one of {sorted(VALID_TIERS)}, got '{tier}'"
        )

    autonomy = _load_yaml(root / "autonomy.yaml")
    _require_keys(
        autonomy,
        ["mode", "max_total_runs", "max_wall_clock_hours", "compute_cap"],
        root / "autonomy.yaml",
    )
    if autonomy["mode"] not in {"supervised", "autonomous"}:
        raise PilotFixtureError(
            f"autonomy.mode must be 'supervised' or 'autonomous', got '{autonomy['mode']}'"
        )

    seeds = _load_yaml(root / "seeds.yaml")
    if not seeds:
        raise PilotFixtureError(f"{root / 'seeds.yaml'} must declare at least one seed")

    expected_path = root / "expected.yaml"
    expected = _load_yaml(expected_path) if expected_path.exists() else {}

    readme_path = root / "README.md"
    if not readme_path.exists():
        raise PilotFixtureError(f"required fixture file missing: {readme_path}")
    readme = readme_path.read_text(encoding="utf-8")

    return PilotFixture(
        problem_id=root.name,
        root=root,
        charter=charter,
        autonomy=autonomy,
        seeds=seeds,
        expected=expected,
        readme=readme,
    )


def list_fixtures(root: Path) -> list[str]:
    """Return the problem_ids of every valid-looking fixture under ``root``.

    Skips entries that do not contain a ``charter.yaml`` -- callers that
    need full validation should call ``load_fixture`` per id.
    """
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "charter.yaml").exists()
    )
