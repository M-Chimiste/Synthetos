"""Checkpoint gate evaluation for the autonomous loop.

All gates are off by default. When a gate fires, the loop_decide operator
pauses its own job and the worker handles the pause/resume lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libs.autonomy.policy import AutonomyPolicy
    from libs.storage.models.autonomy import AutonomyBudget


@dataclass(frozen=True)
class GateContext:
    """State needed to evaluate checkpoint gates."""

    runs_since_last_gate: int
    wall_clock_elapsed_s: float
    next_hardware_profile: dict | None = None
    current_hardware_profile: dict | None = None
    is_result_promotion: bool = False
    has_network_access: bool = False


@dataclass(frozen=True)
class GateResult:
    """Result of gate evaluation."""

    should_pause: bool
    gate_name: str | None = None
    reason: str = ""


def evaluate_gates(
    policy: AutonomyPolicy,
    budget: AutonomyBudget,
    context: GateContext,
) -> GateResult:
    """Evaluate all configured gates and return the first that fires.

    Gates are checked in priority order. Returns immediately on the first hit.
    """
    gates = policy.checkpoint_gates

    # 1. after_every_run -- fires unconditionally
    if gates.after_every_run:
        return GateResult(
            should_pause=True,
            gate_name="after_every_run",
            reason="Gate: pause after every run.",
        )

    # 2. after_every_n_runs
    if (
        gates.after_every_n_runs is not None
        and context.runs_since_last_gate >= gates.after_every_n_runs
    ):
        return GateResult(
            should_pause=True,
            gate_name="after_every_n_runs",
            reason=(
                f"Gate: pause after every {gates.after_every_n_runs} runs "
                f"({context.runs_since_last_gate} since last gate)."
            ),
        )

    # 3. before_hardware_escalation
    if gates.before_hardware_escalation and _is_hardware_escalation(
        context.current_hardware_profile, context.next_hardware_profile
    ):
        return GateResult(
            should_pause=True,
            gate_name="before_hardware_escalation",
            reason="Gate: hardware escalation detected (e.g., GPU count increase).",
        )

    # 4. before_result_promotion
    if gates.before_result_promotion and context.is_result_promotion:
        return GateResult(
            should_pause=True,
            gate_name="before_result_promotion",
            reason="Gate: hypothesis reached validated status, pausing before promotion.",
        )

    # 5. before_network_execution
    if gates.before_network_execution and context.has_network_access:
        return GateResult(
            should_pause=True,
            gate_name="before_network_execution",
            reason="Gate: next run requires network access.",
        )

    return GateResult(should_pause=False)


def _is_hardware_escalation(
    current: dict | None, next_profile: dict | None
) -> bool:
    """Detect whether the next hardware profile represents an escalation."""
    if next_profile is None:
        return False
    if current is None:
        # First run -- no escalation
        return False

    # GPU count increase
    current_gpus = current.get("gpu_count", 0)
    next_gpus = next_profile.get("gpu_count", 0)
    if next_gpus > current_gpus:
        return True

    # Memory increase
    current_mem = current.get("memory_gb", 0)
    next_mem = next_profile.get("memory_gb", 0)
    return next_mem > current_mem
