"""Tests for repetition detection (fingerprinting and near-duplicate logic)."""

from __future__ import annotations

from unittest.mock import MagicMock

from libs.autonomy.repetition import (
    _controls_within_tolerance,
    _extract_numbers,
    fingerprint_spec,
)


def _spec(
    code_plan: dict | None = None,
    controls: list | None = None,
    metrics: list | None = None,
    baseline: dict | None = None,
) -> MagicMock:
    s = MagicMock()
    s.code_plan = code_plan or {"entry_point": "run.py", "files": {"run.py": "print('hi')"}}
    s.controls = controls or [{"learning_rate": 0.01}]
    s.metrics = metrics or [{"name": "accuracy", "direction": "maximize"}]
    s.baseline = baseline or {"accuracy": 0.5}
    return s


class TestFingerprintSpec:
    def test_same_spec_same_fingerprint(self) -> None:
        s1 = _spec()
        s2 = _spec()
        assert fingerprint_spec(s1) == fingerprint_spec(s2)

    def test_different_code_plan_different_fingerprint(self) -> None:
        s1 = _spec(code_plan={"entry_point": "a.py"})
        s2 = _spec(code_plan={"entry_point": "b.py"})
        assert fingerprint_spec(s1) != fingerprint_spec(s2)

    def test_different_controls_different_fingerprint(self) -> None:
        s1 = _spec(controls=[{"lr": 0.01}])
        s2 = _spec(controls=[{"lr": 0.1}])
        assert fingerprint_spec(s1) != fingerprint_spec(s2)

    def test_stable_across_calls(self) -> None:
        s = _spec()
        fp1 = fingerprint_spec(s)
        fp2 = fingerprint_spec(s)
        assert fp1 == fp2

    def test_key_order_does_not_matter(self) -> None:
        s1 = _spec(code_plan={"a": 1, "b": 2})
        s2 = _spec(code_plan={"b": 2, "a": 1})
        assert fingerprint_spec(s1) == fingerprint_spec(s2)


class TestControlsWithinTolerance:
    def test_identical_controls(self) -> None:
        c = [{"lr": 0.01, "batch_size": 32}]
        assert _controls_within_tolerance(c, c) is True

    def test_within_tolerance(self) -> None:
        c1 = [{"lr": 0.01}]
        c2 = [{"lr": 0.0100005}]  # well within 1%
        assert _controls_within_tolerance(c1, c2) is True

    def test_outside_tolerance(self) -> None:
        c1 = [{"lr": 0.01}]
        c2 = [{"lr": 0.02}]  # 100% difference
        assert _controls_within_tolerance(c1, c2) is False

    def test_different_length(self) -> None:
        c1 = [{"lr": 0.01}]
        c2 = [{"lr": 0.01}, {"wd": 0.001}]
        assert _controls_within_tolerance(c1, c2) is False

    def test_both_none(self) -> None:
        assert _controls_within_tolerance(None, None) is True

    def test_one_none(self) -> None:
        assert _controls_within_tolerance([{"lr": 0.01}], None) is False


class TestExtractNumbers:
    def test_flat_dict(self) -> None:
        assert _extract_numbers({"a": 1, "b": 2.5}) == [1.0, 2.5]

    def test_nested_list(self) -> None:
        assert _extract_numbers([1, [2, 3]]) == [1.0, 2.0, 3.0]

    def test_no_numbers(self) -> None:
        assert _extract_numbers({"key": "value"}) == []

    def test_mixed(self) -> None:
        result = _extract_numbers({"a": 1, "b": "text", "c": [2, "x"]})
        assert result == [1.0, 2.0]
