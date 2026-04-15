"""Tests for the directional signal classification algorithm."""

from __future__ import annotations

from libs.remediation.signal_classification import classify_signal


class TestFirstRun:
    def test_no_history_returns_advancing(self) -> None:
        result = classify_signal(0.85, [], "maximize")
        assert result.signal == "advancing"
        assert result.delta is None


class TestAdvancing:
    def test_maximize_improving(self) -> None:
        result = classify_signal(0.90, [0.80, 0.85], "maximize")
        assert result.signal == "advancing"
        assert result.delta is not None
        assert result.delta > 0

    def test_minimize_improving(self) -> None:
        result = classify_signal(0.10, [0.30, 0.20], "minimize")
        assert result.signal == "advancing"
        assert result.delta is not None
        assert result.delta < 0


class TestRegressing:
    def test_maximize_worsening(self) -> None:
        result = classify_signal(0.70, [0.80, 0.85], "maximize")
        assert result.signal == "regressing"

    def test_minimize_worsening(self) -> None:
        result = classify_signal(0.40, [0.30, 0.20], "minimize")
        assert result.signal == "regressing"


class TestStalled:
    def test_within_noise_band(self) -> None:
        result = classify_signal(0.850, [0.848, 0.849], "maximize", noise_band=0.01)
        assert result.signal == "stalled"

    def test_single_prior_within_band(self) -> None:
        # Only one prior value but within noise band
        result = classify_signal(0.850, [0.849], "maximize", noise_band=0.01)
        assert result.signal == "stalled"


class TestNoisy:
    def test_alternating_direction(self) -> None:
        # Up, down, up pattern
        history = [0.80, 0.90, 0.82, 0.91]
        result = classify_signal(0.83, history, "maximize")
        assert result.signal == "noisy"

    def test_not_noisy_with_consistent_direction(self) -> None:
        history = [0.80, 0.82, 0.84, 0.86]
        result = classify_signal(0.88, history, "maximize")
        assert result.signal != "noisy"


class TestBreakthrough:
    def test_large_improvement(self) -> None:
        # Plateau at ~0.50, then jump to 0.80
        history = [0.48, 0.50, 0.51, 0.49]
        result = classify_signal(0.80, history, "maximize")
        assert result.signal == "breakthrough"

    def test_minimize_breakthrough(self) -> None:
        # Plateau at ~0.50, then drop to 0.10
        history = [0.52, 0.50, 0.49, 0.51]
        result = classify_signal(0.10, history, "minimize")
        assert result.signal == "breakthrough"

    def test_not_breakthrough_with_insufficient_history(self) -> None:
        # Only 2 history points — can't compute meaningful stddev
        result = classify_signal(0.90, [0.50, 0.51], "maximize")
        assert result.signal != "breakthrough"

    def test_not_breakthrough_if_regressing(self) -> None:
        # Large move but in wrong direction
        history = [0.48, 0.50, 0.51, 0.49]
        result = classify_signal(0.10, history, "maximize")
        assert result.signal != "breakthrough"


class TestEdgeCases:
    def test_zero_previous_value(self) -> None:
        # Previous value is 0; should not divide by zero
        result = classify_signal(0.5, [0.0], "maximize")
        assert result.signal in ("advancing", "breakthrough")

    def test_identical_values(self) -> None:
        result = classify_signal(0.5, [0.5, 0.5, 0.5], "maximize")
        assert result.signal == "stalled"

    def test_two_data_points(self) -> None:
        result = classify_signal(0.9, [0.8], "maximize")
        assert result.signal == "advancing"
