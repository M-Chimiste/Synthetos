"""Tests for autonomy budget checking logic (pure functions, no DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

from libs.autonomy.budget import (
    check_budget,
    check_per_hypothesis_budget,
)
from libs.autonomy.policy import AutonomyPolicy


def _make_budget(
    total_runs: int = 0,
    wall_clock_elapsed_s: float = 0.0,
    runs_per_hypothesis: dict | None = None,
    started_at: datetime | None = None,
) -> MagicMock:
    """Create a mock AutonomyBudget for testing pure check functions."""
    budget = MagicMock()
    budget.total_runs = total_runs
    budget.wall_clock_elapsed_s = wall_clock_elapsed_s
    budget.runs_per_hypothesis = runs_per_hypothesis or {}
    budget.started_at = started_at or datetime.now(UTC)
    return budget


class TestCheckBudget:
    def test_no_limits_never_exceeded(self) -> None:
        policy = AutonomyPolicy(mode="autonomous")
        budget = _make_budget(total_runs=100, wall_clock_elapsed_s=999999.0)
        result = check_budget(policy, budget)
        assert result.exceeded is False

    def test_total_runs_at_limit(self) -> None:
        policy = AutonomyPolicy(mode="autonomous", max_total_runs=10)
        budget = _make_budget(total_runs=10)
        result = check_budget(policy, budget)
        assert result.exceeded is True
        assert result.limit_name == "max_total_runs"

    def test_total_runs_below_limit(self) -> None:
        policy = AutonomyPolicy(mode="autonomous", max_total_runs=10)
        budget = _make_budget(total_runs=9)
        result = check_budget(policy, budget)
        assert result.exceeded is False

    def test_wall_clock_at_limit(self) -> None:
        policy = AutonomyPolicy(mode="autonomous", max_wall_clock_hours=2.0)
        budget = _make_budget(wall_clock_elapsed_s=7200.0)  # exactly 2 hours
        result = check_budget(policy, budget)
        assert result.exceeded is True
        assert result.limit_name == "max_wall_clock_hours"

    def test_wall_clock_below_limit(self) -> None:
        policy = AutonomyPolicy(mode="autonomous", max_wall_clock_hours=2.0)
        budget = _make_budget(wall_clock_elapsed_s=7199.0)
        result = check_budget(policy, budget)
        assert result.exceeded is False

    def test_total_runs_checked_before_wall_clock(self) -> None:
        """When both limits are exceeded, total_runs is reported first."""
        policy = AutonomyPolicy(
            mode="autonomous", max_total_runs=5, max_wall_clock_hours=1.0
        )
        budget = _make_budget(total_runs=5, wall_clock_elapsed_s=3601.0)
        result = check_budget(policy, budget)
        assert result.exceeded is True
        assert result.limit_name == "max_total_runs"


class TestCheckPerHypothesisBudget:
    def test_no_limit_never_exceeded(self) -> None:
        policy = AutonomyPolicy(mode="autonomous")
        budget = _make_budget(
            runs_per_hypothesis={"abc": 999}
        )
        card_id = UUID("00000000-0000-0000-0000-000000000abc")
        result = check_per_hypothesis_budget(policy, budget, card_id)
        assert result.exceeded is False

    def test_at_limit(self) -> None:
        card_id = UUID("00000000-0000-0000-0000-000000000abc")
        policy = AutonomyPolicy(mode="autonomous", max_runs_per_hypothesis=3)
        budget = _make_budget(
            runs_per_hypothesis={str(card_id): 3}
        )
        result = check_per_hypothesis_budget(policy, budget, card_id)
        assert result.exceeded is True
        assert result.limit_name == "max_runs_per_hypothesis"

    def test_below_limit(self) -> None:
        card_id = UUID("00000000-0000-0000-0000-000000000abc")
        policy = AutonomyPolicy(mode="autonomous", max_runs_per_hypothesis=3)
        budget = _make_budget(
            runs_per_hypothesis={str(card_id): 2}
        )
        result = check_per_hypothesis_budget(policy, budget, card_id)
        assert result.exceeded is False

    def test_new_hypothesis_not_exceeded(self) -> None:
        card_id = UUID("00000000-0000-0000-0000-000000000abc")
        policy = AutonomyPolicy(mode="autonomous", max_runs_per_hypothesis=3)
        budget = _make_budget(runs_per_hypothesis={})
        result = check_per_hypothesis_budget(policy, budget, card_id)
        assert result.exceeded is False
