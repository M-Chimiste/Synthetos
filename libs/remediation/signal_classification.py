"""Pure-function directional signal classification.

Classifies the trend of a primary metric across experiment runs as one of:
advancing, stalled, regressing, noisy, or breakthrough.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class SignalResult:
    """Output of signal classification."""

    signal: str  # advancing | stalled | regressing | noisy | breakthrough
    delta: float | None  # change from previous value (None if first run)
    reasoning: str


def classify_signal(
    current_value: float,
    history: list[float],
    direction: str,
    noise_band: float = 0.01,
) -> SignalResult:
    """Classify the directional signal for a metric.

    Args:
        current_value: The metric value from the current run.
        history: Chronological list of prior metric values (oldest first),
                 excluding the current value.
        direction: "maximize" or "minimize".
        noise_band: Fractional threshold below which changes are noise (default 1%).

    Returns:
        A SignalResult with the classified signal, delta, and reasoning.
    """
    if not history:
        return SignalResult(
            signal="advancing",
            delta=None,
            reasoning="First successful run; no prior data for comparison.",
        )

    prev = history[-1]
    delta = current_value - prev

    # Normalise delta percentage relative to the previous value
    denom = max(abs(prev), 1e-8)
    delta_pct = abs(delta) / denom

    improving = (delta > 0) if direction == "maximize" else (delta < 0)

    # Check for breakthrough (requires >= 3 prior data points for meaningful stddev)
    if len(history) >= 3 and improving:
        mean = statistics.mean(history)
        stdev = statistics.stdev(history)
        if stdev > 0:
            z_score = abs(current_value - mean) / stdev
            if z_score > 2.0:
                return SignalResult(
                    signal="breakthrough",
                    delta=delta,
                    reasoning=(
                        f"Metric moved {z_score:.1f} standard deviations from "
                        f"historical mean ({mean:.4f} ± {stdev:.4f}); "
                        f"current={current_value:.4f}, delta={delta:+.4f}."
                    ),
                )

    # Check for oscillation (noisy) — need >= 3 prior values + current
    if len(history) >= 3:
        recent = [*list(history[-3:]), current_value]
        deltas = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        sign_changes = sum(
            1 for i in range(1, len(deltas)) if deltas[i] * deltas[i - 1] < 0
        )
        # If every consecutive pair flips sign, it's noisy
        if sign_changes >= len(deltas) - 1:
            return SignalResult(
                signal="noisy",
                delta=delta,
                reasoning=(
                    f"Metric direction alternated in {sign_changes} of "
                    f"{len(deltas) - 1} consecutive pairs; current={current_value:.4f}."
                ),
            )

    # Check for stalled — within noise band for 3+ consecutive runs
    if len(history) >= 2 and delta_pct <= noise_band:
        # Check if the last few values were also within noise band
        recent_vals = [*list(history[-2:]), current_value]
        all_within_band = all(
            abs(recent_vals[i] - recent_vals[i - 1]) / max(abs(recent_vals[i - 1]), 1e-8)
            <= noise_band
            for i in range(1, len(recent_vals))
        )
        if all_within_band:
            return SignalResult(
                signal="stalled",
                delta=delta,
                reasoning=(
                    f"Metric within {noise_band:.0%} noise band for "
                    f"{len(recent_vals)} consecutive runs; current={current_value:.4f}."
                ),
            )

    # Simple advancing / regressing based on direction
    if delta_pct <= noise_band:
        # Within noise band but not enough consecutive stalls
        return SignalResult(
            signal="stalled",
            delta=delta,
            reasoning=(
                f"Change of {delta_pct:.1%} is within {noise_band:.0%} noise band; "
                f"current={current_value:.4f}, delta={delta:+.4f}."
            ),
        )

    if improving:
        return SignalResult(
            signal="advancing",
            delta=delta,
            reasoning=(
                f"Metric {'increased' if direction == 'maximize' else 'decreased'} "
                f"by {delta_pct:.1%}; current={current_value:.4f}, delta={delta:+.4f}."
            ),
        )

    return SignalResult(
        signal="regressing",
        delta=delta,
        reasoning=(
            f"Metric moved in wrong direction ({direction}); "
            f"current={current_value:.4f}, delta={delta:+.4f} ({delta_pct:.1%})."
        ),
    )
