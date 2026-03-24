"""Directional signal evaluation: metric trends, frontiers, reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from libs.storage.models import RunRecordModel


class DirectionalSignal(StrEnum):
    """Classifies the directional trend of a metric across runs."""

    ADVANCING = "advancing"
    STALLED = "stalled"
    REGRESSING = "regressing"
    NOISY = "noisy"
    BREAKTHROUGH = "breakthrough"


class MetricPoint(NamedTuple):
    """A single metric observation in a time series."""

    run_public_id: str
    value: float
    created_at: datetime


@dataclass
class FrontierState:
    """Best-known metric value for a hypothesis line."""

    best_value: float
    best_run_public_id: str
    runs_since_improvement: int


def compute_metric_series(
    current_metrics: dict[str, Any],
    prior_runs: list[RunRecordModel],
    metric_name: str,
    current_run_public_id: str,
    current_run_created_at: datetime,
) -> list[MetricPoint]:
    """Build a time-ordered metric series from prior runs plus the current run.

    Runs missing the metric are skipped. The series is ordered oldest-first.
    """
    points: list[MetricPoint] = []

    for run in prior_runs:
        ms = run.metrics_summary or {}
        if metric_name in ms:
            val = ms[metric_name]
            if isinstance(val, (int, float)) and not (val != val):  # skip NaN
                points.append(MetricPoint(
                    run_public_id=run.public_id,
                    value=float(val),
                    created_at=run.created_at,
                ))

    # Add current run
    if metric_name in current_metrics:
        val = current_metrics[metric_name]
        if isinstance(val, (int, float)) and not (val != val):
            points.append(MetricPoint(
                run_public_id=current_run_public_id,
                value=float(val),
                created_at=current_run_created_at,
            ))

    # Sort oldest-first
    points.sort(key=lambda p: p.created_at)
    return points


def classify_direction(
    series: list[MetricPoint],
    higher_is_better: bool,
    significance_threshold: float,
    stall_window: int = 3,
) -> DirectionalSignal:
    """Classify the directional trend of a metric series.

    Args:
        series: Time-ordered metric points (oldest first).
        higher_is_better: Whether larger values are better.
        significance_threshold: Relative threshold for meaningful change (e.g. 0.01 = 1%).
        stall_window: Number of consecutive sub-threshold deltas to declare stall.

    Returns:
        A DirectionalSignal classification.
    """
    if len(series) < 2:
        return DirectionalSignal.NOISY

    values = [p.value for p in series]

    # Compute consecutive deltas (positive = improvement when higher_is_better)
    deltas: list[float] = []
    for i in range(1, len(values)):
        raw_delta = values[i] - values[i - 1]
        deltas.append(raw_delta if higher_is_better else -raw_delta)

    # Relative deltas (as fraction of the reference value)
    rel_deltas: list[float] = []
    for i in range(1, len(values)):
        ref = abs(values[i - 1]) if values[i - 1] != 0 else 1.0
        rel_deltas.append(deltas[i - 1] / ref)

    latest_rel_delta = rel_deltas[-1]

    # --- Breakthrough detection ---
    # Latest improvement exceeds 2× the mean absolute improvement
    if len(rel_deltas) >= 2:
        mean_abs_improvement = sum(abs(d) for d in rel_deltas[:-1]) / len(rel_deltas[:-1])
        threshold = 2.0 * max(mean_abs_improvement, significance_threshold)
        if latest_rel_delta > 0 and latest_rel_delta > threshold:
            return DirectionalSignal.BREAKTHROUGH

    # Single large improvement also counts as breakthrough
    if len(rel_deltas) == 1 and latest_rel_delta > 2.0 * significance_threshold:
        return DirectionalSignal.BREAKTHROUGH

    # --- Stall detection ---
    # Check if the last stall_window deltas are all below threshold
    if len(rel_deltas) >= stall_window:
        recent = rel_deltas[-stall_window:]
        if all(abs(d) < significance_threshold for d in recent):
            return DirectionalSignal.STALLED

    # --- Noise detection ---
    # Direction changes sign more than 50% of the time
    if len(deltas) >= 3:
        sign_changes = sum(
            1 for i in range(1, len(deltas))
            if (deltas[i] > 0) != (deltas[i - 1] > 0) and deltas[i] != 0 and deltas[i - 1] != 0
        )
        if sign_changes / (len(deltas) - 1) > 0.5:
            return DirectionalSignal.NOISY

    # --- Advancing / Regressing based on latest delta ---
    if latest_rel_delta > significance_threshold:
        return DirectionalSignal.ADVANCING

    if latest_rel_delta < -significance_threshold:
        return DirectionalSignal.REGRESSING

    # Sub-threshold but not enough history for stall → default to stalled
    return DirectionalSignal.STALLED


def compute_frontier(
    series: list[MetricPoint],
    higher_is_better: bool,
) -> FrontierState:
    """Compute the running best (frontier) for a metric series.

    Args:
        series: Time-ordered metric points (oldest first).
        higher_is_better: Whether larger values are better.

    Returns:
        FrontierState with best value, best run, and runs since last improvement.
    """
    if not series:
        msg = "Cannot compute frontier from empty series"
        raise ValueError(msg)

    best_value = series[0].value
    best_run_public_id = series[0].run_public_id
    runs_since_improvement = 0

    for point in series[1:]:
        improved = (point.value > best_value) if higher_is_better else (point.value < best_value)
        if improved:
            best_value = point.value
            best_run_public_id = point.run_public_id
            runs_since_improvement = 0
        else:
            runs_since_improvement += 1

    return FrontierState(
        best_value=best_value,
        best_run_public_id=best_run_public_id,
        runs_since_improvement=runs_since_improvement,
    )


def reconcile_signals(
    signal_map: dict[str, DirectionalSignal],
    primary_metric: str,
    constraint_names: list[str],
) -> dict[str, Any]:
    """Reconcile directional signals across primary and constraint metrics.

    Returns a dict with:
        overall: the primary metric's signal
        conflicts: list of {metric, signal, detail} for constraints that conflict
    """
    primary_signal = signal_map.get(primary_metric, DirectionalSignal.NOISY)

    conflicts: list[dict[str, str]] = []
    for name in constraint_names:
        constraint_signal = signal_map.get(name)
        if constraint_signal is None:
            continue

        # Conflict: primary advancing but constraint regressing
        if (
            primary_signal in (DirectionalSignal.ADVANCING, DirectionalSignal.BREAKTHROUGH)
            and constraint_signal == DirectionalSignal.REGRESSING
        ):
            conflicts.append({
                "metric": name,
                "signal": constraint_signal.value,
                "detail": f"Primary metric '{primary_metric}' is {primary_signal.value} but "
                          f"constraint '{name}' is regressing",
            })

    return {
        "overall": primary_signal.value,
        "conflicts": conflicts,
    }
