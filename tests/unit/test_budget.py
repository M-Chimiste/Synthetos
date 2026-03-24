"""Tests for budget checking and tracking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from libs.core.budget import check_budget, copy_budget_from_charter, record_run_usage


def _make_cycle(**overrides: object) -> MagicMock:
    cycle = MagicMock()
    cycle.budget_max_total_runs = None
    cycle.budget_max_compute_minutes = None
    cycle.budget_max_wall_clock_hours = None
    cycle.budget_max_runs_per_hypothesis = None
    cycle.budget_used_compute_minutes = 0.0
    cycle.budget_used_run_count = 0
    cycle.budget_runs_per_hypothesis = {}
    cycle.created_at = datetime.now(UTC)
    for k, v in overrides.items():
        setattr(cycle, k, v)
    return cycle


class TestCheckBudget:
    def test_within_limits(self) -> None:
        cycle = _make_cycle(
            budget_max_total_runs=10,
            budget_used_run_count=3,
        )
        status = check_budget(cycle)
        assert status.within_budget is True
        assert status.remaining_runs == 7

    def test_total_runs_exceeded(self) -> None:
        cycle = _make_cycle(
            budget_max_total_runs=5,
            budget_used_run_count=5,
        )
        status = check_budget(cycle)
        assert status.within_budget is False
        assert "exhausted" in (status.reason or "").lower()

    def test_compute_minutes_exceeded(self) -> None:
        cycle = _make_cycle(
            budget_max_compute_minutes=60,
            budget_used_compute_minutes=65.0,
        )
        status = check_budget(cycle)
        assert status.within_budget is False
        assert "compute" in (status.reason or "").lower()

    def test_per_hypothesis_exceeded(self) -> None:
        cycle = _make_cycle(
            budget_max_runs_per_hypothesis=3,
            budget_runs_per_hypothesis={"hyp-1": 3},
        )
        status = check_budget(cycle, hypothesis_public_id="hyp-1")
        assert status.within_budget is False
        assert "per-hypothesis" in (status.reason or "").lower()

    def test_wall_clock_exceeded(self) -> None:
        cycle = _make_cycle(
            budget_max_wall_clock_hours=1.0,
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        status = check_budget(cycle)
        assert status.within_budget is False
        assert "wall clock" in (status.reason or "").lower()

    def test_no_budget_set(self) -> None:
        cycle = _make_cycle()
        status = check_budget(cycle)
        assert status.within_budget is True
        assert status.remaining_runs is None

    def test_per_hypothesis_within_limits(self) -> None:
        cycle = _make_cycle(
            budget_max_runs_per_hypothesis=5,
            budget_runs_per_hypothesis={"hyp-1": 2},
        )
        status = check_budget(cycle, hypothesis_public_id="hyp-1")
        assert status.within_budget is True
        assert status.hypothesis_runs_remaining == 3


class TestRecordRunUsage:
    def test_increments_counters(self) -> None:
        cycle = _make_cycle(
            budget_used_compute_minutes=10.0,
            budget_used_run_count=2,
            budget_runs_per_hypothesis={"hyp-1": 1},
        )
        run = MagicMock()
        run.started_at = datetime.now(UTC) - timedelta(minutes=5)
        run.completed_at = datetime.now(UTC)

        session = MagicMock()
        record_run_usage(session, cycle, run, "hyp-1")

        assert cycle.budget_used_run_count == 3
        assert cycle.budget_runs_per_hypothesis["hyp-1"] == 2
        assert cycle.budget_used_compute_minutes > 10.0

    def test_handles_missing_timestamps(self) -> None:
        cycle = _make_cycle(budget_used_run_count=0)
        run = MagicMock()
        run.started_at = None
        run.completed_at = None

        session = MagicMock()
        record_run_usage(session, cycle, run, "hyp-1")

        assert cycle.budget_used_run_count == 1
        assert cycle.budget_used_compute_minutes == 0.0


class TestCopyBudgetFromCharter:
    def test_copies_fields(self) -> None:
        charter = MagicMock()
        charter.budget_envelope = {
            "max_compute_hours": 8,
            "max_total_runs": 50,
            "max_wall_clock_hours": 12,
            "max_runs_per_hypothesis": 5,
        }
        cycle = _make_cycle()

        copy_budget_from_charter(charter, cycle)

        assert cycle.budget_max_compute_minutes == 480  # 8 * 60
        assert cycle.budget_max_total_runs == 50
        assert cycle.budget_max_wall_clock_hours == 12
        assert cycle.budget_max_runs_per_hypothesis == 5

    def test_handles_empty_envelope(self) -> None:
        charter = MagicMock()
        charter.budget_envelope = {}
        cycle = _make_cycle()

        copy_budget_from_charter(charter, cycle)

        assert cycle.budget_max_total_runs is None
