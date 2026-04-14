"""Tests for hypothesis lifecycle status transitions."""

from __future__ import annotations

from unittest.mock import MagicMock

from libs.autonomy.hypothesis_lifecycle import STALL_THRESHOLD, compute_lifecycle_status


def _frontier(
    runs_since_improvement: int = 0,
    best_metric_value: float = 0.8,
    primary_metric_direction: str = "maximize",
) -> MagicMock:
    f = MagicMock()
    f.runs_since_improvement = runs_since_improvement
    f.best_metric_value = best_metric_value
    f.primary_metric_direction = primary_metric_direction
    return f


def _spec(stop_conditions: list | None = None) -> MagicMock:
    s = MagicMock()
    s.stop_conditions = stop_conditions
    return s


class TestCompiledTransitions:
    def test_compiled_to_active(self) -> None:
        result = compute_lifecycle_status("compiled", None, None, "continue_current")
        assert result == "active"

    def test_compiled_to_active_on_any_recommendation(self) -> None:
        result = compute_lifecycle_status("compiled", "advancing", None, "parameter_variation")
        assert result == "active"


class TestDeferredTransitions:
    def test_deferred_to_active(self) -> None:
        result = compute_lifecycle_status("deferred", None, None, "continue_current")
        assert result == "active"


class TestActiveTransitions:
    def test_active_to_promising_on_advancing(self) -> None:
        result = compute_lifecycle_status("active", "advancing", _frontier(), "continue_current")
        assert result == "promising"

    def test_active_to_promising_on_breakthrough(self) -> None:
        result = compute_lifecycle_status("active", "breakthrough", _frontier(), "continue_current")
        assert result == "promising"

    def test_active_to_stalled(self) -> None:
        result = compute_lifecycle_status(
            "active",
            "stalled",
            _frontier(runs_since_improvement=STALL_THRESHOLD),
            "continue_current",
        )
        assert result == "stalled"

    def test_active_not_stalled_below_threshold(self) -> None:
        result = compute_lifecycle_status(
            "active",
            "stalled",
            _frontier(runs_since_improvement=STALL_THRESHOLD - 1),
            "continue_current",
        )
        assert result is None

    def test_active_to_deprioritized_on_pivot(self) -> None:
        result = compute_lifecycle_status("active", "stalled", _frontier(), "hypothesis_pivot")
        assert result == "deprioritized"

    def test_active_no_transition_on_noisy(self) -> None:
        result = compute_lifecycle_status("active", "noisy", _frontier(), "continue_current")
        assert result is None

    def test_active_no_transition_on_regressing(self) -> None:
        result = compute_lifecycle_status("active", "regressing", _frontier(), "continue_current")
        assert result is None


class TestPromisingTransitions:
    def test_promising_to_stalled(self) -> None:
        result = compute_lifecycle_status(
            "promising",
            "stalled",
            _frontier(runs_since_improvement=STALL_THRESHOLD),
            "continue_current",
        )
        assert result == "stalled"

    def test_promising_to_validated_meets_threshold(self) -> None:
        spec = _spec(stop_conditions=[{"threshold": 0.9}])
        frontier = _frontier(best_metric_value=0.91, primary_metric_direction="maximize")
        result = compute_lifecycle_status(
            "promising", "advancing", frontier, "continue_current", spec
        )
        assert result == "validated"

    def test_promising_not_validated_below_threshold(self) -> None:
        spec = _spec(stop_conditions=[{"threshold": 0.9}])
        frontier = _frontier(best_metric_value=0.85, primary_metric_direction="maximize")
        result = compute_lifecycle_status(
            "promising", "advancing", frontier, "continue_current", spec
        )
        # Should become promising again (already promising, no-op)
        assert result is None  # already promising, no transition needed

    def test_promising_validated_minimize(self) -> None:
        spec = _spec(stop_conditions=[{"threshold": 0.1}])
        frontier = _frontier(best_metric_value=0.05, primary_metric_direction="minimize")
        result = compute_lifecycle_status(
            "promising", "advancing", frontier, "continue_current", spec
        )
        assert result == "validated"

    def test_promising_no_stop_conditions(self) -> None:
        spec = _spec(stop_conditions=[])
        frontier = _frontier(best_metric_value=0.99)
        result = compute_lifecycle_status(
            "promising", "advancing", frontier, "continue_current", spec
        )
        assert result is None


class TestStalledTransitions:
    def test_stalled_to_deprioritized(self) -> None:
        result = compute_lifecycle_status("stalled", None, None, "hypothesis_pivot")
        assert result == "deprioritized"

    def test_stalled_no_transition_without_pivot(self) -> None:
        result = compute_lifecycle_status("stalled", None, None, "continue_current")
        assert result is None


class TestTerminalStatuses:
    def test_deprioritized_no_transition(self) -> None:
        result = compute_lifecycle_status(
            "deprioritized", "advancing", _frontier(), "continue_current"
        )
        assert result is None

    def test_validated_no_transition(self) -> None:
        result = compute_lifecycle_status("validated", "advancing", _frontier(), "continue_current")
        assert result is None

    def test_rejected_no_transition(self) -> None:
        result = compute_lifecycle_status("rejected", "advancing", _frontier(), "continue_current")
        assert result is None

    def test_candidate_no_transition(self) -> None:
        result = compute_lifecycle_status("candidate", None, None, "continue_current")
        assert result is None
