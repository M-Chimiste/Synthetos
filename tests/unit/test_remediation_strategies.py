"""Tests for remediation strategy selection and tier escalation."""

from __future__ import annotations

from libs.remediation.strategies import _extract_missing_modules, _parse_memory, select_strategy


class TestDependencyStrategy:
    def test_parses_missing_module(self) -> None:
        stderr = "ModuleNotFoundError: No module named 'scikit-learn'\nsome other output"
        result = select_strategy(
            failure_class="dependency",
            stderr_tail=stderr,
            current_resource_limits={},
            prior_strategies=[],
            prior_failure_classes=[],
        )
        assert result.strategy == "install_deps"
        assert result.strategy_tier == "focused"
        assert result.remediable is True
        assert "scikit-learn" in result.overrides["build_recipe"]["extra_pip_packages"]

    def test_escalates_on_retry(self) -> None:
        result = select_strategy(
            failure_class="dependency",
            stderr_tail="ModuleNotFoundError: No module named 'foo'",
            current_resource_limits={},
            prior_strategies=["install_deps"],
            prior_failure_classes=["dependency"],
        )
        assert result.strategy == "debug_broad"
        assert result.strategy_tier == "broad"

    def test_broad_when_no_module_found(self) -> None:
        result = select_strategy(
            failure_class="dependency",
            stderr_tail="some opaque error without module name",
            current_resource_limits={},
            prior_strategies=[],
            prior_failure_classes=[],
        )
        assert result.strategy == "debug_broad"


class TestOOMStrategy:
    def test_doubles_memory(self) -> None:
        result = select_strategy(
            failure_class="oom",
            stderr_tail="",
            current_resource_limits={"memory": "16g"},
            prior_strategies=[],
            prior_failure_classes=[],
        )
        assert result.strategy == "increase_memory"
        assert result.overrides["run_resource_limits"]["memory"] == "32g"

    def test_caps_at_max(self) -> None:
        result = select_strategy(
            failure_class="oom",
            stderr_tail="",
            current_resource_limits={"memory": "64g"},
            prior_strategies=[],
            prior_failure_classes=[],
        )
        assert result.remediable is False

    def test_escalates_on_retry(self) -> None:
        result = select_strategy(
            failure_class="oom",
            stderr_tail="",
            current_resource_limits={"memory": "32g"},
            prior_strategies=["increase_memory"],
            prior_failure_classes=["oom"],
        )
        assert result.strategy == "debug_broad"


class TestTimeoutStrategy:
    def test_increases_timeout(self) -> None:
        result = select_strategy(
            failure_class="timeout",
            stderr_tail="",
            current_resource_limits={"timeout": 3600},
            prior_strategies=[],
            prior_failure_classes=[],
        )
        assert result.strategy == "extend_timeout"
        assert result.overrides["run_resource_limits"]["timeout"] == 5400

    def test_caps_at_max(self) -> None:
        result = select_strategy(
            failure_class="timeout",
            stderr_tail="",
            current_resource_limits={"timeout": 14400},
            prior_strategies=[],
            prior_failure_classes=[],
        )
        assert result.remediable is False


class TestMetricParseStrategy:
    def test_not_remediable(self) -> None:
        result = select_strategy(
            failure_class="metric_parse",
            stderr_tail="",
            current_resource_limits={},
            prior_strategies=[],
            prior_failure_classes=[],
        )
        assert result.remediable is False
        assert result.strategy == "skip"


class TestRuntimeStrategy:
    def test_always_broad_debug(self) -> None:
        result = select_strategy(
            failure_class="runtime",
            stderr_tail="AssertionError: expected shape (10,) but got (5,)",
            current_resource_limits={},
            prior_strategies=[],
            prior_failure_classes=[],
        )
        assert result.strategy == "debug_broad"
        assert result.strategy_tier == "broad"


class TestInvalidArtifactStrategy:
    def test_creates_focused_rewrite_when_mapping_is_unambiguous(self) -> None:
        result = select_strategy(
            failure_class="invalid_artifact",
            stderr_tail="",
            current_resource_limits={},
            prior_strategies=[],
            prior_failure_classes=[],
            expected_artifacts=[
                {"name": "metrics.json", "path": "outputs/metrics.json", "required": True}
            ],
            artifact_manifest=[
                {"name": "results.json", "path": "outputs/results.json", "size_bytes": 42}
            ],
            code_plan={
                "files": {
                    "run_experiment.py": (
                        "with open('outputs/results.json', 'w') as f:\n"
                        "    f.write('ok')\n"
                    )
                }
            },
        )
        assert result.strategy == "repair_artifact_path"
        assert result.strategy_tier == "focused"
        patched = result.overrides["code_plan"]["patched_files"]["run_experiment.py"]
        assert "outputs/metrics.json" in patched

    def test_falls_back_to_broad_when_mapping_is_ambiguous(self) -> None:
        result = select_strategy(
            failure_class="invalid_artifact",
            stderr_tail="",
            current_resource_limits={},
            prior_strategies=[],
            prior_failure_classes=[],
            expected_artifacts=[
                {"name": "metrics.json", "path": "outputs/metrics.json", "required": True}
            ],
            artifact_manifest=[
                {"name": "results.json", "path": "outputs/results.json"},
                {"name": "summary.json", "path": "outputs/summary.json"},
            ],
            code_plan={
                "files": {
                    "run_experiment.py": "print('artifact paths are dynamic')\n"
                }
            },
        )
        assert result.strategy == "debug_broad"


class TestDifferentFailureClassOnRetry:
    def test_uses_focused_for_new_class(self) -> None:
        # First attempt was dependency, second is oom → use focused for oom
        result = select_strategy(
            failure_class="oom",
            stderr_tail="",
            current_resource_limits={"memory": "16g"},
            prior_strategies=["install_deps"],
            prior_failure_classes=["dependency"],
        )
        assert result.strategy == "increase_memory"
        assert result.strategy_tier == "focused"


class TestHelpers:
    def test_extract_missing_modules(self) -> None:
        stderr = (
            "Traceback...\n"
            "ModuleNotFoundError: No module named 'numpy'\n"
            "ImportError: No module named 'pandas.core'\n"
        )
        result = _extract_missing_modules(stderr)
        assert "numpy" in result
        assert "pandas" in result  # top-level extracted from pandas.core
        assert len(result) == 2

    def test_parse_memory(self) -> None:
        assert _parse_memory("16g") == 16
        assert _parse_memory("2048m") == 2
        assert _parse_memory("32") == 32
