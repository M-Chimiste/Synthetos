"""Tests for autonomy policy parsing and budget logic."""

from __future__ import annotations

from libs.autonomy.policy import AutonomyPolicy, CheckpointGateConfig


class TestAutonomyPolicyDefaults:
    def test_default_mode_is_supervised(self) -> None:
        policy = AutonomyPolicy()
        assert policy.mode == "supervised"

    def test_default_no_budget_limits(self) -> None:
        policy = AutonomyPolicy()
        assert policy.max_total_runs is None
        assert policy.max_wall_clock_hours is None
        assert policy.max_runs_per_hypothesis is None
        assert policy.max_wall_time_per_run_s is None

    def test_default_gates_all_off(self) -> None:
        policy = AutonomyPolicy()
        gates = policy.checkpoint_gates
        assert gates.after_every_run is False
        assert gates.after_every_n_runs is None
        assert gates.before_hardware_escalation is False
        assert gates.before_result_promotion is False
        assert gates.before_network_execution is False

    def test_default_summary_interval(self) -> None:
        policy = AutonomyPolicy()
        assert policy.summary_interval == 5


class TestAutonomyPolicyFromDict:
    def test_parse_autonomous_mode(self) -> None:
        policy = AutonomyPolicy.model_validate({"mode": "autonomous"})
        assert policy.mode == "autonomous"

    def test_parse_with_budgets(self) -> None:
        policy = AutonomyPolicy.model_validate({
            "mode": "autonomous",
            "max_total_runs": 20,
            "max_wall_clock_hours": 4.0,
            "max_runs_per_hypothesis": 5,
        })
        assert policy.max_total_runs == 20
        assert policy.max_wall_clock_hours == 4.0
        assert policy.max_runs_per_hypothesis == 5

    def test_parse_with_gates(self) -> None:
        policy = AutonomyPolicy.model_validate({
            "checkpoint_gates": {
                "after_every_n_runs": 3,
                "before_hardware_escalation": True,
            }
        })
        assert policy.checkpoint_gates.after_every_n_runs == 3
        assert policy.checkpoint_gates.before_hardware_escalation is True
        assert policy.checkpoint_gates.after_every_run is False

    def test_parse_empty_dict_uses_defaults(self) -> None:
        policy = AutonomyPolicy.model_validate({})
        assert policy.mode == "supervised"
        assert policy.max_total_runs is None

    def test_extra_fields_ignored(self) -> None:
        policy = AutonomyPolicy.model_validate({
            "mode": "autonomous",
            "unknown_field": True,
        })
        assert policy.mode == "autonomous"


class TestCheckpointGateConfig:
    def test_all_defaults(self) -> None:
        config = CheckpointGateConfig()
        assert config.after_every_run is False
        assert config.after_every_n_runs is None
        assert config.before_hardware_escalation is False
        assert config.before_result_promotion is False
        assert config.before_network_execution is False
