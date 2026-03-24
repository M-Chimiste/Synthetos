"""Tests for directional signal evaluation: trends, frontiers, reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from libs.schemas.domain import SuccessCriteria
from libs.verification.trend import (
    DirectionalSignal,
    MetricPoint,
    classify_direction,
    compute_frontier,
    compute_metric_series,
    reconcile_signals,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(public_id: str, metrics: dict, minutes_ago: int) -> MagicMock:
    run = MagicMock()
    run.public_id = public_id
    run.metrics_summary = metrics
    run.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return run


def _make_series(values: list[float], higher_is_better: bool = True) -> list[MetricPoint]:
    """Build a simple time-ordered series for testing classify_direction."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        MetricPoint(f"run-{i}", v, base + timedelta(hours=i))
        for i, v in enumerate(values)
    ]


# ---------------------------------------------------------------------------
# compute_metric_series
# ---------------------------------------------------------------------------


class TestComputeMetricSeries:
    def test_with_prior_runs(self) -> None:
        prior = [
            _make_run("run-1", {"accuracy": 0.80}, 30),
            _make_run("run-2", {"accuracy": 0.82}, 20),
        ]
        series = compute_metric_series(
            {"accuracy": 0.85}, prior, "accuracy", "run-3", datetime.now(UTC),
        )
        assert len(series) == 3
        # Oldest first
        assert series[0].value == pytest.approx(0.80)
        assert series[-1].value == pytest.approx(0.85)

    def test_skips_missing_metric(self) -> None:
        prior = [
            _make_run("run-1", {"accuracy": 0.80}, 30),
            _make_run("run-2", {"loss": 0.5}, 20),  # no accuracy
        ]
        series = compute_metric_series(
            {"accuracy": 0.85}, prior, "accuracy", "run-3", datetime.now(UTC),
        )
        assert len(series) == 2
        assert series[0].run_public_id == "run-1"
        assert series[1].run_public_id == "run-3"

    def test_single_run_no_prior(self) -> None:
        series = compute_metric_series(
            {"accuracy": 0.90}, [], "accuracy", "run-1", datetime.now(UTC),
        )
        assert len(series) == 1
        assert series[0].value == pytest.approx(0.90)

    def test_skips_nan(self) -> None:
        prior = [_make_run("run-1", {"accuracy": float("nan")}, 10)]
        series = compute_metric_series(
            {"accuracy": 0.85}, prior, "accuracy", "run-2", datetime.now(UTC),
        )
        assert len(series) == 1


# ---------------------------------------------------------------------------
# classify_direction
# ---------------------------------------------------------------------------


class TestClassifyDirection:
    def test_advancing(self) -> None:
        # Steady improvement: 0.80, 0.82, 0.85, 0.88
        series = _make_series([0.80, 0.82, 0.85, 0.88])
        signal = classify_direction(series, higher_is_better=True, significance_threshold=0.01)
        assert signal == DirectionalSignal.ADVANCING

    def test_stalled(self) -> None:
        # Flat: 0.85, 0.851, 0.849, 0.850
        series = _make_series([0.85, 0.851, 0.849, 0.850])
        signal = classify_direction(series, higher_is_better=True, significance_threshold=0.01)
        assert signal == DirectionalSignal.STALLED

    def test_regressing(self) -> None:
        # Declining: 0.90, 0.88, 0.85, 0.82
        series = _make_series([0.90, 0.88, 0.85, 0.82])
        signal = classify_direction(series, higher_is_better=True, significance_threshold=0.01)
        assert signal == DirectionalSignal.REGRESSING

    def test_noisy(self) -> None:
        # Alternating: up, down, up, down
        series = _make_series([0.80, 0.85, 0.78, 0.86, 0.77])
        signal = classify_direction(series, higher_is_better=True, significance_threshold=0.01)
        assert signal == DirectionalSignal.NOISY

    def test_breakthrough(self) -> None:
        # Small improvements then a big jump
        series = _make_series([0.80, 0.81, 0.82, 0.95])
        signal = classify_direction(series, higher_is_better=True, significance_threshold=0.01)
        assert signal == DirectionalSignal.BREAKTHROUGH

    def test_insufficient_data(self) -> None:
        series = _make_series([0.85])
        signal = classify_direction(series, higher_is_better=True, significance_threshold=0.01)
        assert signal == DirectionalSignal.NOISY

    def test_lower_is_better(self) -> None:
        # Loss decreasing = advancing
        series = _make_series([1.5, 1.3, 1.1, 0.9])
        signal = classify_direction(series, higher_is_better=False, significance_threshold=0.01)
        assert signal == DirectionalSignal.ADVANCING

    def test_lower_is_better_regressing(self) -> None:
        # Loss increasing = regressing
        series = _make_series([0.5, 0.6, 0.7, 0.8])
        signal = classify_direction(series, higher_is_better=False, significance_threshold=0.01)
        assert signal == DirectionalSignal.REGRESSING

    def test_two_points_big_improvement_is_breakthrough(self) -> None:
        series = _make_series([0.50, 0.80])
        signal = classify_direction(series, higher_is_better=True, significance_threshold=0.01)
        assert signal == DirectionalSignal.BREAKTHROUGH

    def test_empty_series(self) -> None:
        signal = classify_direction([], higher_is_better=True, significance_threshold=0.01)
        assert signal == DirectionalSignal.NOISY


# ---------------------------------------------------------------------------
# compute_frontier
# ---------------------------------------------------------------------------


class TestComputeFrontier:
    def test_finds_best(self) -> None:
        series = _make_series([0.80, 0.85, 0.82, 0.90])
        frontier = compute_frontier(series, higher_is_better=True)
        assert frontier.best_value == pytest.approx(0.90)
        assert frontier.best_run_public_id == "run-3"
        assert frontier.runs_since_improvement == 0

    def test_runs_since_improvement(self) -> None:
        series = _make_series([0.80, 0.90, 0.85, 0.82])
        frontier = compute_frontier(series, higher_is_better=True)
        assert frontier.best_value == pytest.approx(0.90)
        assert frontier.best_run_public_id == "run-1"
        assert frontier.runs_since_improvement == 2

    def test_lower_is_better(self) -> None:
        series = _make_series([1.5, 1.0, 1.2, 0.8])
        frontier = compute_frontier(series, higher_is_better=False)
        assert frontier.best_value == pytest.approx(0.8)
        assert frontier.runs_since_improvement == 0

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty series"):
            compute_frontier([], higher_is_better=True)


# ---------------------------------------------------------------------------
# reconcile_signals
# ---------------------------------------------------------------------------


class TestReconcileSignals:
    def test_no_conflicts(self) -> None:
        signal_map = {
            "accuracy": DirectionalSignal.ADVANCING,
            "latency": DirectionalSignal.ADVANCING,
        }
        result = reconcile_signals(signal_map, "accuracy", ["latency"])
        assert result["overall"] == "advancing"
        assert result["conflicts"] == []

    def test_with_conflict(self) -> None:
        signal_map = {
            "accuracy": DirectionalSignal.ADVANCING,
            "latency": DirectionalSignal.REGRESSING,
        }
        result = reconcile_signals(signal_map, "accuracy", ["latency"])
        assert result["overall"] == "advancing"
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["metric"] == "latency"

    def test_no_constraints(self) -> None:
        signal_map = {"accuracy": DirectionalSignal.STALLED}
        result = reconcile_signals(signal_map, "accuracy", [])
        assert result["overall"] == "stalled"
        assert result["conflicts"] == []

    def test_breakthrough_with_constraint_regression(self) -> None:
        signal_map = {
            "accuracy": DirectionalSignal.BREAKTHROUGH,
            "memory_mb": DirectionalSignal.REGRESSING,
        }
        result = reconcile_signals(signal_map, "accuracy", ["memory_mb"])
        assert len(result["conflicts"]) == 1

    def test_stalled_constraint_no_conflict(self) -> None:
        signal_map = {
            "accuracy": DirectionalSignal.ADVANCING,
            "latency": DirectionalSignal.STALLED,
        }
        result = reconcile_signals(signal_map, "accuracy", ["latency"])
        assert result["conflicts"] == []


# ---------------------------------------------------------------------------
# SuccessCriteria schema
# ---------------------------------------------------------------------------


class TestSuccessCriteria:
    def test_valid_input(self) -> None:
        sc = SuccessCriteria.model_validate({
            "primary_metric": "val_accuracy",
            "primary_higher_is_better": True,
            "significance_threshold": 0.005,
            "stall_window": 5,
            "constraint_metrics": [
                {"name": "inference_time_ms", "higher_is_better": False, "upper_bound": 100},
            ],
        })
        assert sc.primary_metric == "val_accuracy"
        assert sc.significance_threshold == 0.005
        assert len(sc.constraint_metrics) == 1
        assert sc.constraint_metrics[0].upper_bound == 100

    def test_defaults(self) -> None:
        sc = SuccessCriteria(primary_metric="accuracy")
        assert sc.primary_higher_is_better is True
        assert sc.significance_threshold == 0.01
        assert sc.stall_window == 3
        assert sc.constraint_metrics == []
