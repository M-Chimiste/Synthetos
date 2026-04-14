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
    from libs.storage.models.experiment import ExperimentSpec


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


@dataclass(frozen=True)
class NextSpecPreview:
    """Concrete pre-execution preview for the next spec."""

    spec_id: str | None
    hardware_profile: dict | None = None
    has_network_access: bool = False


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


def preview_next_spec(spec: ExperimentSpec | None) -> NextSpecPreview:
    """Extract concrete gate-relevant properties from a spec."""
    if spec is None:
        return NextSpecPreview(spec_id=None)

    return NextSpecPreview(
        spec_id=str(spec.id),
        hardware_profile=spec.hardware_profile,
        has_network_access=_detect_network_access(spec),
    )


def _detect_network_access(spec: ExperimentSpec) -> bool:
    """Best-effort detection of whether the next spec needs network access."""
    code_plan = spec.code_plan or {}
    build_recipe = spec.build_recipe or {}

    explicit_flags = [
        code_plan.get("requires_network"),
        code_plan.get("network_access"),
        build_recipe.get("requires_network"),
        build_recipe.get("network_access"),
    ]
    if any(bool(flag) for flag in explicit_flags):
        return True

    text_blobs: list[str] = []
    files = code_plan.get("files", {})
    if isinstance(files, dict):
        text_blobs.extend(str(content) for content in files.values())
    for value in (
        code_plan.get("entry_point"),
        code_plan.get("dependencies"),
        code_plan.get("instructions"),
        build_recipe.get("dockerfile_content"),
    ):
        if value is not None:
            text_blobs.append(str(value))

    heuristics = ("requests.", "httpx.", "urllib.request", "https://", "http://", "wget ", "curl ")
    return any(marker in blob for blob in text_blobs for marker in heuristics)
