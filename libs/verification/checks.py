"""Deterministic verification checks — no LLM calls, pure functions."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def check_artifacts_present(
    artifact_manifest: dict[str, Any],
    expected_outputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Check that expected artifacts exist and are parseable.

    Returns list of ``{artifact_name, present, parseable, detail}``.
    """
    results: list[dict[str, Any]] = []

    # Check well-known paths from the manifest
    for key in ("metrics_path", "checkpoint_path", "predictions_path"):
        path_str = artifact_manifest.get(key)
        if path_str is None:
            continue
        path = Path(str(path_str))
        present = path.exists()
        parseable = False
        detail = ""
        if present:
            try:
                json.loads(path.read_text(encoding="utf-8"))
                parseable = True
            except (json.JSONDecodeError, OSError) as exc:
                detail = str(exc)
        else:
            detail = "file not found"
        results.append({
            "artifact_name": key.replace("_path", ""),
            "present": present,
            "parseable": parseable,
            "detail": detail,
        })

    # Check expected outputs from ExperimentSpec
    for expected in expected_outputs:
        name = expected.get("name", "unknown")
        artifact_path = expected.get("path")
        if artifact_path:
            p = Path(str(artifact_path))
            present = p.exists()
        else:
            # Check if the artifact is listed in manifest artifacts list
            manifest_artifacts = artifact_manifest.get("artifacts", [])
            present = any(a.get("name") == name for a in manifest_artifacts)
        results.append({
            "artifact_name": name,
            "present": present,
            "parseable": present,  # assume parseable if present for spec outputs
            "detail": "" if present else "expected output not found",
        })

    return results


def check_output_contract(
    artifact_manifest: dict[str, Any],
    expected_outputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate that declared outputs are present and parseable where possible."""
    known_paths = {
        Path(str(value)).name: Path(str(value))
        for key, value in artifact_manifest.items()
        if key.endswith("_path") and value
    }
    manifest_artifacts = {
        str(artifact.get("name")): artifact
        for artifact in artifact_manifest.get("artifacts", [])
        if artifact.get("name")
    }
    manifest_artifact_paths = {
        Path(str(artifact.get("path"))).name: Path(str(artifact.get("path")))
        for artifact in artifact_manifest.get("artifacts", [])
        if artifact.get("path")
    }
    results: list[dict[str, Any]] = []

    for expected in expected_outputs:
        name = str(expected.get("name", "unknown"))
        declared_path = expected.get("path")
        manifest_artifact = manifest_artifacts.get(name, {})
        manifest_path_match = manifest_artifact_paths.get(name)
        artifact_path = declared_path or manifest_artifact.get("path")
        if artifact_path is None and manifest_path_match is not None:
            artifact_path = str(manifest_path_match)
        if artifact_path is None and name in known_paths:
            artifact_path = str(known_paths[name])
        path = Path(str(artifact_path)) if artifact_path else None
        present = (
            path.exists()
            if path is not None
            else bool(
                manifest_artifact
                or manifest_artifact_paths.get(name)
                or known_paths.get(name)
            )
        )
        parseable = present
        detail = ""

        if present and path is not None and path.suffix.lower() == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                parseable = False
                detail = str(exc)
        elif not present:
            detail = "declared output missing from artifact manifest"

        results.append({
            "output_name": name,
            "path": str(path) if path is not None else None,
            "present": present,
            "parseable": parseable,
            "passed": present and parseable,
            "detail": detail or "output contract satisfied",
        })

    return results


def check_metric_sanity(
    metrics_summary: dict[str, Any],
    expected_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate metric values: present, not NaN, within optional bounds.

    Returns list of ``{check_name, passed, detail}``.
    """
    results: list[dict[str, Any]] = []

    for spec in expected_metrics:
        name = spec.get("name", "unknown")
        value = metrics_summary.get(name)

        if value is None:
            results.append({
                "check_name": f"{name}_present",
                "passed": False,
                "detail": f"Metric '{name}' not found in metrics summary",
            })
            continue

        # Presence check passed
        results.append({
            "check_name": f"{name}_present",
            "passed": True,
            "detail": f"value={value}",
        })

        # NaN check
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            results.append({
                "check_name": f"{name}_finite",
                "passed": False,
                "detail": f"Metric '{name}' is NaN or Inf",
            })
            continue

        results.append({
            "check_name": f"{name}_finite",
            "passed": True,
            "detail": f"value={value}",
        })

        # Bounds check
        lower = spec.get("lower_bound")
        upper = spec.get("upper_bound")
        if lower is not None and isinstance(value, (int, float)) and value < lower:
            results.append({
                "check_name": f"{name}_in_bounds",
                "passed": False,
                "detail": f"{value} < lower bound {lower}",
            })
        elif upper is not None and isinstance(value, (int, float)) and value > upper:
            results.append({
                "check_name": f"{name}_in_bounds",
                "passed": False,
                "detail": f"{value} > upper bound {upper}",
            })
        elif lower is not None or upper is not None:
            results.append({
                "check_name": f"{name}_in_bounds",
                "passed": True,
                "detail": f"value={value} within [{lower}, {upper}]",
            })

    return results


def compare_to_baseline(
    metrics_summary: dict[str, Any],
    baseline_description: str,
    declared_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare run metrics against declared baseline.

    Returns ``{metric, run_value, baseline_value, delta, delta_pct, passed}``.
    """
    # Extract baseline value from the first declared metric with a baseline_value
    primary_metric = None
    baseline_value = None
    higher_is_better = True

    for spec in declared_metrics:
        if "baseline_value" in spec:
            primary_metric = spec.get("name")
            baseline_value = spec.get("baseline_value")
            higher_is_better = spec.get("higher_is_better", True)
            break

    if primary_metric is None or baseline_value is None:
        return {
            "metric": None,
            "run_value": None,
            "baseline_value": None,
            "delta": None,
            "delta_pct": None,
            "passed": True,  # No baseline to compare against
            "detail": "No baseline metric declared in experiment spec",
        }

    run_value = metrics_summary.get(primary_metric)
    if run_value is None:
        return {
            "metric": primary_metric,
            "run_value": None,
            "baseline_value": baseline_value,
            "delta": None,
            "delta_pct": None,
            "passed": False,
            "detail": f"Run metric '{primary_metric}' not found",
        }

    delta = run_value - baseline_value
    delta_pct = (delta / abs(baseline_value) * 100) if baseline_value != 0 else 0.0
    passed = (delta >= 0) if higher_is_better else (delta <= 0)

    return {
        "metric": primary_metric,
        "run_value": run_value,
        "baseline_value": baseline_value,
        "delta": round(delta, 6),
        "delta_pct": round(delta_pct, 2),
        "passed": passed,
    }


def check_leakage_signals(
    metrics_summary: dict[str, Any],
    experiment_spec_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Heuristic checks for data leakage or evaluation contamination.

    Returns list of ``{signal_name, detected, detail}``.
    """
    signals: list[dict[str, Any]] = []

    # Check for suspiciously perfect metrics
    for key, value in metrics_summary.items():
        if isinstance(value, (int, float)):
            if key.lower() in ("accuracy", "auc", "f1", "precision", "recall"):
                if value == 1.0:
                    signals.append({
                        "signal_name": f"perfect_{key}",
                        "detected": True,
                        "detail": f"{key}=1.0 may indicate leakage or trivial task",
                    })
            if key.lower() in ("loss", "error", "mse", "mae", "rmse"):
                if value == 0.0:
                    signals.append({
                        "signal_name": f"zero_{key}",
                        "detected": True,
                        "detail": f"{key}=0.0 may indicate leakage or overfitting",
                    })

    # Check train/val gap if both present
    train_acc = metrics_summary.get("train_accuracy")
    val_acc = metrics_summary.get("val_accuracy") or metrics_summary.get("accuracy")
    if train_acc is not None and val_acc is not None:
        gap = abs(train_acc - val_acc)
        if gap < 0.001 and train_acc > 0.99:
            signals.append({
                "signal_name": "train_val_gap_suspicious",
                "detected": True,
                "detail": (
                    f"train_accuracy={train_acc}, val_accuracy={val_acc}"
                    " — nearly identical at high level"
                ),
            })

    if not signals:
        signals.append({
            "signal_name": "no_leakage_signals",
            "detected": False,
            "detail": "No obvious leakage indicators found",
        })

    return signals


def validate_split(
    metrics_summary: dict[str, Any],
    experiment_spec_data: dict[str, Any],
) -> dict[str, Any]:
    """Validate that the evaluation split matches the declared spec.

    Returns ``{intended_split, actual_split, matched}``.
    """
    # Extract intended split from experiment spec datasets
    datasets = experiment_spec_data.get("datasets", [])
    intended_split = None
    for ds in datasets:
        if ds.get("role") in ("validation", "test", "eval"):
            intended_split = ds.get("split") or ds.get("name")
            break

    actual_split = metrics_summary.get("eval_split") or metrics_summary.get("split")

    if intended_split is None and actual_split is None:
        return {
            "intended_split": None,
            "actual_split": None,
            "matched": True,
            "detail": "No split information declared or reported",
        }

    matched = True
    if intended_split and actual_split:
        matched = str(intended_split).lower() == str(actual_split).lower()

    return {
        "intended_split": intended_split,
        "actual_split": actual_split,
        "matched": matched,
    }
