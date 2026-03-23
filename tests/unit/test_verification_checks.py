"""Unit tests for Phase 4 verification checks and outcome determination."""

from __future__ import annotations

import json
from pathlib import Path

from libs.verification.checks import (
    check_artifacts_present,
    check_leakage_signals,
    check_metric_sanity,
    check_output_contract,
    compare_to_baseline,
    validate_split,
)
from libs.verification.outcome import VerificationOutcome, determine_outcome
from libs.verification.recommendations import build_next_step_recommendations

# ---------------------------------------------------------------------------
# check_artifacts_present
# ---------------------------------------------------------------------------


def test_check_artifacts_present_all_found(tmp_path: Path):
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"accuracy": 0.9}), encoding="utf-8")
    manifest = {
        "metrics_path": str(metrics),
    }
    results = check_artifacts_present(manifest, [])
    assert len(results) == 1
    assert results[0]["artifact_name"] == "metrics"
    assert results[0]["present"] is True
    assert results[0]["parseable"] is True


def test_check_artifacts_present_missing(tmp_path: Path):
    manifest = {
        "metrics_path": str(tmp_path / "missing.json"),
    }
    results = check_artifacts_present(manifest, [])
    assert len(results) == 1
    assert results[0]["present"] is False


def test_check_artifacts_present_expected_outputs(tmp_path: Path):
    results = check_artifacts_present(
        {"artifacts": [{"name": "model_weights"}]},
        [
            {"name": "model_weights"},
            {"name": "evaluation_log"},
        ],
    )
    found = {r["artifact_name"]: r["present"] for r in results}
    assert found["model_weights"] is True
    assert found["evaluation_log"] is False


# ---------------------------------------------------------------------------
# check_metric_sanity
# ---------------------------------------------------------------------------


def test_check_metric_sanity_pass():
    metrics = {"accuracy": 0.85, "loss": 0.15}
    expected = [
        {"name": "accuracy", "lower_bound": 0.0, "upper_bound": 1.0},
        {"name": "loss", "lower_bound": 0.0, "upper_bound": 10.0},
    ]
    results = check_metric_sanity(metrics, expected)
    assert all(r["passed"] for r in results)


def test_check_metric_sanity_nan():
    metrics = {"accuracy": float("nan")}
    expected = [{"name": "accuracy"}]
    results = check_metric_sanity(metrics, expected)
    failed = [r for r in results if not r["passed"]]
    assert len(failed) >= 1
    assert any("NaN" in r["detail"] for r in failed)


def test_check_metric_sanity_out_of_bounds():
    metrics = {"accuracy": 1.5}
    expected = [{"name": "accuracy", "upper_bound": 1.0}]
    results = check_metric_sanity(metrics, expected)
    failed = [r for r in results if not r["passed"]]
    assert len(failed) >= 1
    assert any("upper bound" in r["detail"] for r in failed)


def test_check_metric_sanity_missing():
    metrics = {}
    expected = [{"name": "accuracy"}]
    results = check_metric_sanity(metrics, expected)
    assert not results[0]["passed"]
    assert "not found" in results[0]["detail"]


# ---------------------------------------------------------------------------
# check_output_contract
# ---------------------------------------------------------------------------


def test_check_output_contract_passes_with_manifest_path(tmp_path: Path):
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"accuracy": 0.9}), encoding="utf-8")
    results = check_output_contract(
        {
            "metrics_path": str(metrics),
            "artifacts": [{"name": "metrics", "path": str(metrics)}],
        },
        [{"name": "metrics.json"}],
    )
    assert results[0]["passed"] is True


def test_check_output_contract_missing_output():
    results = check_output_contract(
        {"artifacts": []},
        [{"name": "metrics.json"}],
    )
    assert results[0]["passed"] is False


# ---------------------------------------------------------------------------
# compare_to_baseline
# ---------------------------------------------------------------------------


def test_compare_to_baseline_improvement():
    metrics = {"accuracy": 0.92}
    declared = [
        {"name": "accuracy", "baseline_value": 0.85, "higher_is_better": True}
    ]
    result = compare_to_baseline(metrics, "Random forest baseline", declared)
    assert result["passed"] is True
    assert result["delta"] > 0
    assert result["metric"] == "accuracy"


def test_compare_to_baseline_regression():
    metrics = {"accuracy": 0.80}
    declared = [
        {"name": "accuracy", "baseline_value": 0.85, "higher_is_better": True}
    ]
    result = compare_to_baseline(metrics, "Random forest baseline", declared)
    assert result["passed"] is False
    assert result["delta"] < 0


def test_compare_to_baseline_no_baseline():
    metrics = {"accuracy": 0.80}
    declared = [{"name": "accuracy"}]  # No baseline_value
    result = compare_to_baseline(metrics, "", declared)
    assert result["passed"] is True
    assert result["metric"] is None


# ---------------------------------------------------------------------------
# check_leakage_signals
# ---------------------------------------------------------------------------


def test_check_leakage_signals_perfect_accuracy():
    signals = check_leakage_signals({"accuracy": 1.0}, {})
    detected = [s for s in signals if s["detected"]]
    assert len(detected) >= 1
    assert any("perfect" in s["signal_name"] for s in detected)


def test_check_leakage_signals_clean():
    signals = check_leakage_signals({"accuracy": 0.87}, {})
    detected = [s for s in signals if s["detected"]]
    assert len(detected) == 0


# ---------------------------------------------------------------------------
# validate_split
# ---------------------------------------------------------------------------


def test_validate_split_matched():
    result = validate_split(
        {"eval_split": "test"},
        {"datasets": [{"role": "validation", "split": "test"}]},
    )
    assert result["matched"] is True


def test_validate_split_mismatch():
    result = validate_split(
        {"eval_split": "train"},
        {"datasets": [{"role": "validation", "split": "test"}]},
    )
    assert result["matched"] is False


def test_validate_split_no_info():
    result = validate_split({}, {"datasets": []})
    assert result["matched"] is True


# ---------------------------------------------------------------------------
# determine_outcome
# ---------------------------------------------------------------------------


def test_determine_outcome_robust():
    outcome = determine_outcome(
        run_status="succeeded",
        baseline_comparison={
            "metric": "accuracy",
            "passed": True,
            "delta_pct": 5.0,
        },
        metric_sanity_checks=[{"passed": True}],
        artifact_checks=[{"artifact_name": "metrics", "present": True}],
        leakage_signals=[{"detected": False}],
        split_validation={"matched": True},
        historical_comparisons=[
            {"prior_run_public_id": "run_1", "delta": 0.02}
        ],
    )
    assert outcome == VerificationOutcome.ROBUST


def test_determine_outcome_tentative():
    outcome = determine_outcome(
        run_status="succeeded",
        baseline_comparison={
            "metric": "accuracy",
            "passed": True,
            "delta_pct": 0.5,  # marginal improvement
        },
        metric_sanity_checks=[{"passed": True}],
        artifact_checks=[],
        leakage_signals=[{"detected": False}],
        split_validation={"matched": True},
        historical_comparisons=[],
    )
    assert outcome == VerificationOutcome.TENTATIVE


def test_determine_outcome_rejected_leakage():
    outcome = determine_outcome(
        run_status="succeeded",
        baseline_comparison={"metric": "accuracy", "passed": True},
        metric_sanity_checks=[{"passed": True}],
        artifact_checks=[],
        leakage_signals=[{"detected": True}],
        split_validation={"matched": True},
        historical_comparisons=[],
    )
    assert outcome == VerificationOutcome.REJECTED


def test_determine_outcome_rejected_baseline_regression():
    outcome = determine_outcome(
        run_status="succeeded",
        baseline_comparison={
            "metric": "accuracy",
            "passed": False,
        },
        metric_sanity_checks=[{"passed": True}],
        artifact_checks=[],
        leakage_signals=[{"detected": False}],
        split_validation={"matched": True},
        historical_comparisons=[],
    )
    assert outcome == VerificationOutcome.REJECTED


def test_determine_outcome_invalid_failed_run():
    outcome = determine_outcome(
        run_status="failed",
        baseline_comparison={},
        metric_sanity_checks=[],
        artifact_checks=[],
        leakage_signals=[],
        split_validation={},
        historical_comparisons=[],
    )
    assert outcome == VerificationOutcome.INVALID


def test_determine_outcome_invalid_nan_metric():
    outcome = determine_outcome(
        run_status="succeeded",
        baseline_comparison={},
        metric_sanity_checks=[
            {"passed": False, "detail": "Metric 'loss' is NaN or Inf"}
        ],
        artifact_checks=[],
        leakage_signals=[{"detected": False}],
        split_validation={"matched": True},
        historical_comparisons=[],
    )
    assert outcome == VerificationOutcome.INVALID


def test_determine_outcome_invalid_missing_critical_artifact():
    outcome = determine_outcome(
        run_status="succeeded",
        baseline_comparison={},
        metric_sanity_checks=[],
        artifact_checks=[
            {"artifact_name": "metrics", "present": False},
        ],
        leakage_signals=[{"detected": False}],
        split_validation={"matched": True},
        historical_comparisons=[],
    )
    assert outcome == VerificationOutcome.INVALID


def test_determine_outcome_rejected_split_mismatch():
    outcome = determine_outcome(
        run_status="succeeded",
        baseline_comparison={},
        metric_sanity_checks=[],
        artifact_checks=[],
        leakage_signals=[{"detected": False}],
        split_validation={"matched": False},
        historical_comparisons=[],
    )
    assert outcome == VerificationOutcome.REJECTED


def test_determine_outcome_policy_requires_history_for_robust():
    outcome = determine_outcome(
        run_status="succeeded",
        baseline_comparison={"metric": "accuracy", "passed": True, "delta_pct": 5.0},
        metric_sanity_checks=[{"passed": True}],
        artifact_checks=[],
        output_contract_checks=[],
        leakage_signals=[{"detected": False}],
        split_validation={"matched": True},
        historical_comparisons=[],
        require_historical_comparison=True,
    )
    assert outcome == VerificationOutcome.TENTATIVE


def test_build_next_step_recommendations_returns_follow_up_search():
    recommendations = build_next_step_recommendations(
        outcome="rejected",
        min_outcome_for_promotion="tentative",
        rerun_note="Revise before rerunning.",
        retrieval_hints=[{"query": "data leakage detection", "rationale": "Relevant"}],
        protocol_update_hints=[{"field": "datasets", "suggestion": "Use held-out split"}],
        reviewer_summary="Verification rejected the run.",
    )
    kinds = {item["recommendation_type"] for item in recommendations}
    assert "revise_protocol" in kinds
    assert "follow_up_search" in kinds
