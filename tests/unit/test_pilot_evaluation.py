"""Tests for pilot evaluation comparison helpers."""

from __future__ import annotations

from uuid_utils import uuid7

from libs.pilot.evaluation import EvaluationResult, compare_evaluations


def test_compare_evaluations_surfaces_numeric_deltas_and_pass_change() -> None:
    left = EvaluationResult(
        problem_id="ml_baseline_small",
        cycle_id=uuid7(),
        cycle_status="closed",
        passed=False,
        checks={"successful_runs": 1, "patterns_touched": 2},
        warnings=["warning"],
    )
    right = EvaluationResult(
        problem_id="ml_baseline_small",
        cycle_id=uuid7(),
        cycle_status="closed",
        passed=True,
        checks={"successful_runs": 3, "patterns_touched": 5},
        warnings=[],
    )

    comparison = compare_evaluations(left, right)

    assert comparison.deltas["successful_runs"] == 2.0
    assert comparison.deltas["patterns_touched"] == 3.0
    assert "right run passed where left did not" in comparison.summary
