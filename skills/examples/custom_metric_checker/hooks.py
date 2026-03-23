"""Example hook implementation for the custom metric checker skill."""

from __future__ import annotations

from typing import Any


def post_operator(context: dict[str, Any]) -> dict[str, Any]:
    """Called after the run_verify operator completes.

    Checks custom metrics from the run's metrics.json against configured thresholds.
    Returns additional check results to be appended to the verification report.
    """
    metrics = context.get("metrics", {})
    config = context.get("skill_config", {})
    custom_metrics = config.get("custom_metrics", {})

    results: list[dict[str, Any]] = []
    for metric_name, thresholds in custom_metrics.items():
        value = metrics.get(metric_name)
        if value is None:
            results.append({
                "metric": metric_name,
                "status": "missing",
                "message": f"Metric '{metric_name}' not found in run output",
            })
            continue

        lower_is_better = thresholds.get("lower_is_better", False)
        warn = thresholds.get("warn_threshold")
        fail = thresholds.get("fail_threshold")

        status = "pass"
        if fail is not None:
            if (lower_is_better and value > fail) or (not lower_is_better and value < fail):
                status = "fail"
        if warn is not None and status == "pass":
            if (lower_is_better and value > warn) or (not lower_is_better and value < warn):
                status = "warn"

        results.append({
            "metric": metric_name,
            "value": value,
            "status": status,
            "thresholds": thresholds,
        })

    return {"custom_metric_checks": results}
