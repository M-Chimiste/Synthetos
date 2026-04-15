"""Metric contract: deterministic parsing and normalization of container output.

Experiment containers write metrics to /artifacts/metrics.json.  This module
provides the parsing boundary that makes VerificationReport reliable.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParsedMetrics:
    """Result of parsing container metric output."""

    values: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


@dataclass
class MetricVerdict:
    """Pass/fail verdict for a single metric."""

    name: str
    value: float
    baseline_value: float | None = None
    delta: float | None = None
    direction: str = "maximize"
    passed: bool = True
    detail: str = ""


def parse_metrics(
    artifacts_dir: Path,
    expected_metrics: list[dict[str, Any]],
) -> ParsedMetrics:
    """Read /artifacts/metrics.json and validate against expected metrics.

    Rules:
    1. File must exist and be valid JSON
    2. Each expected metric name must be present
    3. Each value must be a finite float (not NaN, not inf)
    4. Extra metrics are kept but flagged as warnings
    5. Type coercion: int -> float is allowed
    """
    result = ParsedMetrics()
    metrics_path = artifacts_dir / "metrics.json"

    if not metrics_path.exists():
        result.errors.append("metrics file missing: /artifacts/metrics.json not found")
        return result

    try:
        raw = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result.errors.append(f"metrics file corrupt: {exc}")
        return result

    if not isinstance(raw, dict):
        result.errors.append("metrics file must be a flat JSON object {name: value}")
        return result

    expected_names = {m["name"] for m in expected_metrics if "name" in m}

    for key, value in raw.items():
        if isinstance(value, int):
            value = float(value)
        if not isinstance(value, float):
            result.errors.append(
                f"metric '{key}': value {value!r} is not numeric (type {type(value).__name__})"
            )
            continue
        if math.isnan(value) or math.isinf(value):
            result.errors.append(f"metric '{key}': value is {value} (NaN/inf not allowed)")
            continue
        result.values[key] = value

    # Check for missing expected metrics
    for name in expected_names:
        if name not in result.values:
            result.errors.append(f"expected metric '{name}' not found in metrics output")

    # Flag extra metrics
    extra = set(result.values.keys()) - expected_names
    for name in sorted(extra):
        result.warnings.append(f"extra metric '{name}' not in expected metrics")

    return result


def classify_metric(
    name: str,
    value: float,
    spec_metric: dict[str, Any],
    baseline_metrics: dict[str, Any] | None = None,
) -> MetricVerdict:
    """Compare a single parsed metric value against its spec definition.

    spec_metric has: {name, direction: maximize|minimize, threshold?: float}
    """
    direction = spec_metric.get("direction", "maximize")
    threshold = spec_metric.get("threshold")
    baseline_value = None
    delta = None

    if baseline_metrics and name in baseline_metrics:
        baseline_value = float(baseline_metrics[name])
        delta = value - baseline_value

    passed = True
    detail = ""

    if threshold is not None:
        threshold = float(threshold)
        if direction == "maximize":
            passed = value >= threshold
            detail = f"value {value:.4f} {'≥' if passed else '<'} threshold {threshold:.4f}"
        else:
            passed = value <= threshold
            detail = f"value {value:.4f} {'≤' if passed else '>'} threshold {threshold:.4f}"
    elif baseline_value is not None:
        detail = f"value {value:.4f}, baseline {baseline_value:.4f}, delta {delta:+.4f}"
    else:
        detail = f"value {value:.4f} (informational; no threshold defined)"

    return MetricVerdict(
        name=name,
        value=value,
        baseline_value=baseline_value,
        delta=delta,
        direction=direction,
        passed=passed,
        detail=detail,
    )
