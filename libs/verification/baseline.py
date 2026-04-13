"""Baseline comparison logic for verification reports."""

from __future__ import annotations

from typing import Any

from libs.execution.metrics import MetricVerdict, classify_metric


def compare_to_baseline(
    run_metrics: dict[str, float],
    spec_metrics: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> list[MetricVerdict]:
    """Compare run metrics against the spec baseline.

    Returns a list of MetricVerdict for each expected metric.
    """
    baseline_expected = baseline.get("expected_metrics", {})
    verdicts = []

    for spec_metric in spec_metrics:
        name = spec_metric.get("name", "")
        value = run_metrics.get(name)
        if value is None:
            verdicts.append(MetricVerdict(
                name=name,
                value=0.0,
                passed=False,
                detail=f"metric '{name}' not found in run output",
            ))
            continue

        verdict = classify_metric(
            name=name,
            value=value,
            spec_metric=spec_metric,
            baseline_metrics=baseline_expected,
        )
        verdicts.append(verdict)

    return verdicts
