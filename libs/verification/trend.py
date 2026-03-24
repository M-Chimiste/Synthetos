"""Directional signal evaluation: metric trends, frontiers, reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import sqrt
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


@dataclass
class DirectionAssessment:
    """Trend classification plus the diagnostics that drove it."""

    signal: DirectionalSignal
    diagnostics: dict[str, Any]


def compute_metric_series(
    current_metrics: dict[str, Any],
    prior_runs: list[RunRecordModel],
    metric_name: str,
    current_run_public_id: str,
    current_run_created_at: datetime,
) -> list[MetricPoint]:
    """Build a time-ordered metric series from prior runs plus the current run."""
    points: list[MetricPoint] = []

    for run in prior_runs:
        metrics_summary = run.metrics_summary or {}
        if metric_name not in metrics_summary:
            continue
        value = metrics_summary[metric_name]
        if isinstance(value, (int, float)) and not (value != value):
            points.append(MetricPoint(
                run_public_id=run.public_id,
                value=float(value),
                created_at=run.created_at,
            ))

    value = current_metrics.get(metric_name)
    if isinstance(value, (int, float)) and not (value != value):
        points.append(MetricPoint(
            run_public_id=current_run_public_id,
            value=float(value),
            created_at=current_run_created_at,
        ))

    points.sort(key=lambda point: point.created_at)
    return points


def compute_frontier(
    series: list[MetricPoint],
    higher_is_better: bool,
) -> FrontierState:
    """Compute the running best (frontier) for a metric series."""
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


def _oriented_values(series: list[MetricPoint], higher_is_better: bool) -> list[float]:
    return [point.value if higher_is_better else -point.value for point in series]


def _relative_delta(new_value: float, old_value: float) -> float:
    denominator = abs(old_value) if old_value != 0 else 1.0
    return (new_value - old_value) / denominator


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = _mean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return sqrt(max(variance, 0.0))


def _linear_regression_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    xs = list(range(len(values)))
    x_mean = _mean(xs)
    y_mean = _mean(values)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values, strict=True))
    return numerator / denominator


def _mann_kendall_tau(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    concordant = 0
    discordant = 0
    for index, left in enumerate(values[:-1]):
        for right in values[index + 1:]:
            if right > left:
                concordant += 1
            elif right < left:
                discordant += 1
    total_pairs = len(values) * (len(values) - 1) / 2
    if total_pairs == 0:
        return 0.0
    return (concordant - discordant) / total_pairs


def _coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean_value = _mean(values)
    if abs(mean_value) < 1e-12:
        return None
    return _stddev(values) / abs(mean_value)


def assess_direction(
    series: list[MetricPoint],
    higher_is_better: bool,
    significance_threshold: float,
    stall_window: int = 3,
    *,
    threshold_source: str = "default",
) -> DirectionAssessment:
    """Classify a metric series and return the diagnostics behind the decision."""
    if len(series) < 2:
        return DirectionAssessment(
            signal=DirectionalSignal.NOISY,
            diagnostics={
                "sample_size": len(series),
                "slope": 0.0,
                "normalized_slope": 0.0,
                "mann_kendall_tau": 0.0,
                "coefficient_of_variation": None,
                "frontier_delta": 0.0,
                "frontier_delta_ratio": 0.0,
                "recent_change_ratio": 0.0,
                "runs_since_improvement": 0,
                "significance_threshold": significance_threshold,
                "threshold_source": threshold_source,
                "reasons": ["Insufficient history for a stable directional judgment."],
            },
        )

    oriented = _oriented_values(series, higher_is_better)
    frontier = compute_frontier(series, higher_is_better)
    slope = _linear_regression_slope(oriented)
    mean_value = _mean(oriented)
    normalized_slope = slope / (abs(mean_value) if abs(mean_value) > 1e-12 else 1.0)
    tau = _mann_kendall_tau(oriented)
    cv = _coefficient_of_variation(oriented)
    recent_change_ratio = _relative_delta(oriented[-1], oriented[-2])

    deltas = [
        _relative_delta(oriented[idx], oriented[idx - 1])
        for idx in range(1, len(oriented))
    ]
    recent_window = min(max(stall_window, 1), len(deltas))
    recent_deltas = deltas[-recent_window:]
    recent_abs_changes = [abs(delta) for delta in recent_deltas]

    sign_changes = 0
    non_zero_steps = 0
    previous_sign = 0
    for delta in deltas:
        if abs(delta) < 1e-12:
            continue
        current_sign = 1 if delta > 0 else -1
        if previous_sign and current_sign != previous_sign:
            sign_changes += 1
        previous_sign = current_sign
        non_zero_steps += 1
    sign_change_ratio = sign_changes / max(non_zero_steps - 1, 1) if non_zero_steps > 1 else 0.0

    prior_best = max(oriented[:-1]) if oriented[:-1] else oriented[-1]
    frontier_delta = oriented[-1] - prior_best
    frontier_delta_ratio = frontier_delta / (abs(prior_best) if abs(prior_best) > 1e-12 else 1.0)

    mean_prior_positive = (
        _mean([delta for delta in deltas[:-1] if delta > 0])
        if len(deltas) > 1
        else 0.0
    )

    reasons: list[str] = []
    signal = DirectionalSignal.STALLED

    if (
        frontier_delta_ratio > max(2 * significance_threshold, 2 * mean_prior_positive)
        and tau >= 0.5
        and recent_change_ratio > significance_threshold
    ):
        signal = DirectionalSignal.BREAKTHROUGH
        reasons.append(
            "Latest point created a frontier jump that is materially larger than prior gains."
        )
    elif (
        sign_change_ratio >= 0.5
        and abs(tau) < 0.5
        and (cv or 0.0) >= max(significance_threshold * 2, 0.02)
    ):
        signal = DirectionalSignal.NOISY
        reasons.append("Series oscillates with weak monotonic evidence and elevated variability.")
    elif (
        len(recent_abs_changes) >= recent_window
        and all(change < significance_threshold for change in recent_abs_changes)
        and abs(normalized_slope) < significance_threshold
        and frontier.runs_since_improvement >= max(recent_window - 1, 0)
    ):
        signal = DirectionalSignal.STALLED
        reasons.append(
            "Recent movement stays below the significance threshold and the frontier is flat."
        )
    elif normalized_slope <= -significance_threshold or tau <= -0.6:
        signal = DirectionalSignal.REGRESSING
        reasons.append("Regression slope and rank trend both point downward.")
    elif (
        normalized_slope >= significance_threshold
        or tau >= 0.6
        or frontier_delta_ratio > significance_threshold
    ):
        signal = DirectionalSignal.ADVANCING
        reasons.append("Slope, monotonic trend, or frontier progress shows sustained improvement.")
    else:
        fallback_noise = (
            sign_change_ratio >= 0.5
            and abs(recent_change_ratio) >= significance_threshold
        )
        signal = DirectionalSignal.NOISY if fallback_noise else DirectionalSignal.STALLED
        if signal == DirectionalSignal.NOISY:
            reasons.append("Trend direction remains unstable after applying the threshold tests.")
        else:
            reasons.append(
                "Signal is below threshold without clear advancing or regressing evidence."
            )

    diagnostics = {
        "sample_size": len(series),
        "slope": slope,
        "normalized_slope": normalized_slope,
        "mann_kendall_tau": tau,
        "coefficient_of_variation": cv,
        "frontier_delta": frontier_delta,
        "frontier_delta_ratio": frontier_delta_ratio,
        "recent_change_ratio": recent_change_ratio,
        "runs_since_improvement": frontier.runs_since_improvement,
        "significance_threshold": significance_threshold,
        "threshold_source": threshold_source,
        "reasons": reasons,
    }
    return DirectionAssessment(signal=signal, diagnostics=diagnostics)


def classify_direction(
    series: list[MetricPoint],
    higher_is_better: bool,
    significance_threshold: float,
    stall_window: int = 3,
) -> DirectionalSignal:
    """Backward-compatible directional signal classification."""
    return assess_direction(
        series,
        higher_is_better,
        significance_threshold,
        stall_window,
    ).signal


def reconcile_signals(
    signal_map: dict[str, DirectionalSignal],
    primary_metric: str,
    constraint_metrics: list[Any],
    metric_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile directional signals across primary and constraint metrics."""
    primary_signal = signal_map.get(primary_metric, DirectionalSignal.NOISY)
    metric_values = metric_values or {}

    conflicts: list[dict[str, Any]] = []
    for constraint in constraint_metrics:
        if isinstance(constraint, str):
            metric_name = constraint
            lower_bound = None
            upper_bound = None
        else:
            metric_name = str(getattr(constraint, "name", ""))
            lower_bound = getattr(constraint, "lower_bound", None)
            upper_bound = getattr(constraint, "upper_bound", None)

        if not metric_name:
            continue

        constraint_signal = signal_map.get(metric_name)
        value = metric_values.get(metric_name)
        violates_bound = False
        if isinstance(value, (int, float)):
            if lower_bound is not None and value < lower_bound:
                violates_bound = True
            if upper_bound is not None and value > upper_bound:
                violates_bound = True

        if (
            primary_signal in (DirectionalSignal.ADVANCING, DirectionalSignal.BREAKTHROUGH)
            and (
                constraint_signal == DirectionalSignal.REGRESSING
                or violates_bound
            )
        ):
            detail = (
                f"Primary metric '{primary_metric}' is {primary_signal.value} but constraint "
                f"'{metric_name}' is {constraint_signal.value if constraint_signal else 'violated'}"
            )
            if violates_bound:
                detail += " and outside its configured bound"
            conflicts.append({
                "metric": metric_name,
                "signal": constraint_signal.value if constraint_signal else "violated",
                "value": float(value) if isinstance(value, (int, float)) else None,
                "lower_bound": lower_bound,
                "upper_bound": upper_bound,
                "violates_bound": violates_bound,
                "detail": detail,
            })

    return {
        "overall": primary_signal.value,
        "conflicts": conflicts,
    }
