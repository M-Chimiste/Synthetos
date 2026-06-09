"""Tests for the deterministic recommendation rules."""

from __future__ import annotations

from libs.remediation.recommendations import (
    STALL_THRESHOLD,
    RecommendationInputs,
    compute_recommendation,
)


def _inputs(**overrides) -> RecommendationInputs:
    """Create RecommendationInputs with sensible defaults."""
    defaults = {
        "signal": "advancing",
        "runs_since_improvement": 0,
        "total_runs": 5,
        "successful_runs": 4,
        "remediation_attempts": 0,
        "remediation_exhausted": False,
        "has_unresolved_failures": False,
        "failed": False,
    }
    defaults.update(overrides)
    return RecommendationInputs(**defaults)


class TestBreakthrough:
    def test_breakthrough_continues(self) -> None:
        result = compute_recommendation(_inputs(signal="breakthrough"))
        assert result.recommendation_type == "continue_current"


class TestAdvancing:
    def test_advancing_no_failures(self) -> None:
        result = compute_recommendation(_inputs(signal="advancing"))
        assert result.recommendation_type == "continue_current"

    def test_advancing_with_unresolved_failures(self) -> None:
        result = compute_recommendation(
            _inputs(signal="advancing", has_unresolved_failures=True)
        )
        assert result.recommendation_type == "parameter_variation"


class TestStalled:
    def test_stalled_below_threshold(self) -> None:
        result = compute_recommendation(
            _inputs(signal="stalled", runs_since_improvement=2)
        )
        assert result.recommendation_type == "parameter_variation"

    def test_stalled_at_threshold(self) -> None:
        result = compute_recommendation(
            _inputs(signal="stalled", runs_since_improvement=STALL_THRESHOLD)
        )
        assert result.recommendation_type == "hypothesis_pivot"

    def test_stalled_above_threshold(self) -> None:
        result = compute_recommendation(
            _inputs(signal="stalled", runs_since_improvement=STALL_THRESHOLD + 3)
        )
        assert result.recommendation_type == "hypothesis_pivot"


class TestRegressing:
    def test_regressing(self) -> None:
        result = compute_recommendation(_inputs(signal="regressing"))
        assert result.recommendation_type == "parameter_variation"


class TestNoisy:
    def test_noisy(self) -> None:
        result = compute_recommendation(_inputs(signal="noisy"))
        assert result.recommendation_type == "parameter_variation"


class TestFailedPath:
    def test_exhausted_no_prior_successes(self) -> None:
        result = compute_recommendation(
            _inputs(
                failed=True,
                signal=None,
                remediation_exhausted=True,
                remediation_attempts=3,
                successful_runs=0,
                total_runs=4,
            )
        )
        assert result.recommendation_type == "hypothesis_pivot"

    def test_exhausted_with_prior_successes(self) -> None:
        result = compute_recommendation(
            _inputs(
                failed=True,
                signal=None,
                remediation_exhausted=True,
                remediation_attempts=3,
                successful_runs=3,
                total_runs=6,
            )
        )
        assert result.recommendation_type == "parameter_variation"

    def test_unresolved_failure_with_prior_successes_varies_parameters(self) -> None:
        result = compute_recommendation(
            _inputs(
                failed=True,
                signal=None,
                remediation_exhausted=False,
                successful_runs=2,
            )
        )
        assert result.recommendation_type == "parameter_variation"

    def test_unresolved_failure_with_no_successes_pivots(self) -> None:
        result = compute_recommendation(
            _inputs(
                failed=True,
                signal=None,
                remediation_exhausted=False,
                successful_runs=0,
            )
        )
        assert result.recommendation_type == "hypothesis_pivot"


class TestFallback:
    def test_unknown_signal(self) -> None:
        result = compute_recommendation(_inputs(signal="unknown_signal"))
        assert result.recommendation_type == "parameter_variation"
