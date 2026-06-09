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


def _as_finite_float(value: Any) -> float | None:
    if isinstance(value, int):
        value = float(value)
    if not isinstance(value, float):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _preferred_nested_group(
    raw: dict[str, Any],
    expected_names: set[str],
) -> tuple[str, dict[str, Any]] | None:
    """Choose a nested metric group to canonicalize into the flat contract.

    Research scripts often compare a baseline against a treatment and emit:
    {"standard": {...}, "diffusionblocks": {...}}.  The verifier still needs
    flat metrics such as "final_perplexity", so prefer treatment-like groups.
    """
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    preferred_markers = (
        "diffusion",
        "treatment",
        "variant",
        "method",
        "experiment",
        "model",
    )
    baseline_markers = ("baseline", "standard", "control")

    for group_name, group_value in raw.items():
        if not isinstance(group_value, dict):
            continue
        numeric_expected = {
            name for name in expected_names if _as_finite_float(group_value.get(name)) is not None
        }
        if not numeric_expected:
            continue
        lowered = group_name.lower()
        score = len(numeric_expected) * 10
        if any(marker in lowered for marker in preferred_markers):
            score += 5
        if any(marker in lowered for marker in baseline_markers):
            score -= 3
        candidates.append((score, group_name, group_value))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, group_name, group_value = candidates[0]
    return group_name, group_value


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

    preferred_group = _preferred_nested_group(raw, expected_names)
    if preferred_group is not None:
        group_name, group_value = preferred_group
        for metric_name in expected_names:
            if metric_name not in raw and metric_name in group_value:
                value = _as_finite_float(group_value.get(metric_name))
                if value is not None:
                    result.values[metric_name] = value
        result.warnings.append(
            f"canonicalized flat metrics from nested group '{group_name}'"
        )

    for key, value in raw.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                numeric_value = _as_finite_float(nested_value)
                if numeric_value is not None:
                    result.values[f"{key}.{nested_key}"] = numeric_value
            if key not in expected_names:
                result.warnings.append(
                    f"extra metric group '{key}' flattened with namespaced keys"
                )
                continue
        numeric = _as_finite_float(value)
        if numeric is None:
            if key not in expected_names:
                result.warnings.append(
                    f"extra metric '{key}' ignored because value is not numeric "
                    f"(type {type(value).__name__})"
                )
                continue
            result.errors.append(
                f"metric '{key}': value {value!r} is not numeric (type {type(value).__name__})"
            )
            continue
        result.values[key] = numeric

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
