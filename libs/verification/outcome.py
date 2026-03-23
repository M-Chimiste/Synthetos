"""Deterministic verification outcome determination."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class VerificationOutcome(StrEnum):
    ROBUST = "robust"
    TENTATIVE = "tentative"
    REJECTED = "rejected"
    INVALID = "invalid"


def determine_outcome(
    *,
    run_status: str,
    baseline_comparison: dict[str, Any],
    metric_sanity_checks: list[dict[str, Any]],
    artifact_checks: list[dict[str, Any]],
    output_contract_checks: list[dict[str, Any]] | None = None,
    leakage_signals: list[dict[str, Any]],
    split_validation: dict[str, Any],
    historical_comparisons: list[dict[str, Any]],
    require_baseline_comparison: bool = False,
    require_historical_comparison: bool = False,
    leakage_check_enabled: bool = True,
    split_validation_enabled: bool = True,
) -> VerificationOutcome:
    """Determine verification outcome from check results.

    Decision logic:
    - INVALID: run failed, critical artifacts missing, or metrics unparseable
    - REJECTED: leakage detected, split mismatch, or regression below baseline
    - TENTATIVE: passes checks but no historical comparison or marginal improvement
    - ROBUST: passes all checks, meets/beats baseline, consistent with history
    """
    # INVALID: run didn't complete successfully
    output_contract_checks = output_contract_checks or []
    if run_status in ("failed", "cancelled"):
        return VerificationOutcome.INVALID

    # INVALID: critical artifacts missing
    missing_critical = any(
        not c.get("present", True)
        for c in artifact_checks
        if c.get("artifact_name") in ("metrics", "predictions")
    )
    if missing_critical:
        return VerificationOutcome.INVALID

    # INVALID: any metric is NaN/Inf
    sanity_failures = [c for c in metric_sanity_checks if not c.get("passed", True)]
    if sanity_failures:
        return VerificationOutcome.INVALID
    nan_failures = [
        c for c in sanity_failures if "NaN" in c.get("detail", "") or "Inf" in c.get("detail", "")
    ]
    if nan_failures:
        return VerificationOutcome.INVALID

    if any(not c.get("passed", True) for c in output_contract_checks):
        return VerificationOutcome.INVALID

    # REJECTED: leakage detected
    leakage_detected = leakage_check_enabled and any(
        c.get("detected", False) for c in leakage_signals
    )
    if leakage_detected:
        return VerificationOutcome.REJECTED

    # REJECTED: split mismatch
    if split_validation_enabled and not split_validation.get("matched", True):
        return VerificationOutcome.REJECTED

    # REJECTED: baseline regression (only if baseline comparison was possible)
    baseline_metric = baseline_comparison.get("metric")
    if baseline_metric is not None and not baseline_comparison.get("passed", True):
        return VerificationOutcome.REJECTED

    # TENTATIVE vs ROBUST
    has_historical = len(historical_comparisons) > 0
    has_baseline = baseline_metric is not None

    if not has_baseline and not has_historical:
        # No comparison data available — tentative by default
        return VerificationOutcome.TENTATIVE

    if require_baseline_comparison and not has_baseline:
        return VerificationOutcome.TENTATIVE

    if require_historical_comparison and not has_historical:
        return VerificationOutcome.TENTATIVE

    # Check if improvement is marginal (< 1% delta)
    if has_baseline:
        delta_pct = baseline_comparison.get("delta_pct", 0)
        if isinstance(delta_pct, (int, float)) and abs(delta_pct) < 1.0:
            return VerificationOutcome.TENTATIVE

    # If we have both baseline and historical comparisons with decent improvement
    if has_baseline and has_historical:
        return VerificationOutcome.ROBUST

    # Has baseline with good improvement but no history
    if has_baseline:
        return VerificationOutcome.TENTATIVE

    # Has history but no baseline
    return VerificationOutcome.TENTATIVE
