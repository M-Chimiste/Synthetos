"""Tests for checkpoint gate evaluation."""

from __future__ import annotations

from unittest.mock import MagicMock

from libs.autonomy.gates import GateContext, _is_hardware_escalation, evaluate_gates
from libs.autonomy.policy import AutonomyPolicy, CheckpointGateConfig


def _budget() -> MagicMock:
    b = MagicMock()
    b.total_runs = 10
    b.wall_clock_elapsed_s = 3600.0
    return b


def _context(**kwargs) -> GateContext:
    defaults = {
        "runs_since_last_gate": 1,
        "wall_clock_elapsed_s": 3600.0,
    }
    defaults.update(kwargs)
    return GateContext(**defaults)


class TestAllGatesOff:
    def test_default_policy_no_pause(self) -> None:
        policy = AutonomyPolicy(mode="autonomous")
        result = evaluate_gates(policy, _budget(), _context())
        assert result.should_pause is False


class TestAfterEveryRun:
    def test_fires(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(after_every_run=True),
        )
        result = evaluate_gates(policy, _budget(), _context())
        assert result.should_pause is True
        assert result.gate_name == "after_every_run"


class TestAfterEveryNRuns:
    def test_fires_at_threshold(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(after_every_n_runs=3),
        )
        result = evaluate_gates(policy, _budget(), _context(runs_since_last_gate=3))
        assert result.should_pause is True
        assert result.gate_name == "after_every_n_runs"

    def test_does_not_fire_below_threshold(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(after_every_n_runs=3),
        )
        result = evaluate_gates(policy, _budget(), _context(runs_since_last_gate=2))
        assert result.should_pause is False


class TestBeforeHardwareEscalation:
    def test_fires_on_gpu_increase(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(before_hardware_escalation=True),
        )
        ctx = _context(
            current_hardware_profile={"gpu_count": 1},
            next_hardware_profile={"gpu_count": 2},
        )
        result = evaluate_gates(policy, _budget(), ctx)
        assert result.should_pause is True
        assert result.gate_name == "before_hardware_escalation"

    def test_does_not_fire_on_same_hardware(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(before_hardware_escalation=True),
        )
        ctx = _context(
            current_hardware_profile={"gpu_count": 1},
            next_hardware_profile={"gpu_count": 1},
        )
        result = evaluate_gates(policy, _budget(), ctx)
        assert result.should_pause is False

    def test_does_not_fire_when_no_next_profile(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(before_hardware_escalation=True),
        )
        ctx = _context(
            current_hardware_profile={"gpu_count": 1},
            next_hardware_profile=None,
        )
        result = evaluate_gates(policy, _budget(), ctx)
        assert result.should_pause is False


class TestBeforeResultPromotion:
    def test_fires(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(before_result_promotion=True),
        )
        ctx = _context(is_result_promotion=True)
        result = evaluate_gates(policy, _budget(), ctx)
        assert result.should_pause is True
        assert result.gate_name == "before_result_promotion"

    def test_does_not_fire_when_not_promoting(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(before_result_promotion=True),
        )
        ctx = _context(is_result_promotion=False)
        result = evaluate_gates(policy, _budget(), ctx)
        assert result.should_pause is False


class TestBeforeNetworkExecution:
    def test_fires(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(before_network_execution=True),
        )
        ctx = _context(has_network_access=True)
        result = evaluate_gates(policy, _budget(), ctx)
        assert result.should_pause is True
        assert result.gate_name == "before_network_execution"

    def test_does_not_fire_without_network(self) -> None:
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(before_network_execution=True),
        )
        ctx = _context(has_network_access=False)
        result = evaluate_gates(policy, _budget(), ctx)
        assert result.should_pause is False


class TestGatePriority:
    def test_after_every_run_takes_priority(self) -> None:
        """When multiple gates fire, after_every_run is reported first."""
        policy = AutonomyPolicy(
            mode="autonomous",
            checkpoint_gates=CheckpointGateConfig(
                after_every_run=True,
                before_result_promotion=True,
            ),
        )
        ctx = _context(is_result_promotion=True)
        result = evaluate_gates(policy, _budget(), ctx)
        assert result.gate_name == "after_every_run"


class TestHardwareEscalationDetection:
    def test_gpu_count_increase(self) -> None:
        assert _is_hardware_escalation({"gpu_count": 1}, {"gpu_count": 2}) is True

    def test_memory_increase(self) -> None:
        assert _is_hardware_escalation({"memory_gb": 16}, {"memory_gb": 32}) is True

    def test_no_change(self) -> None:
        assert _is_hardware_escalation({"gpu_count": 1}, {"gpu_count": 1}) is False

    def test_none_next(self) -> None:
        assert _is_hardware_escalation({"gpu_count": 1}, None) is False

    def test_none_current(self) -> None:
        assert _is_hardware_escalation(None, {"gpu_count": 1}) is False
