"""Autonomy policy models.

Stored in ``ResearchCycle.config["autonomy"]`` and loaded via
``AutonomyPolicy.model_validate(cycle.config.get("autonomy", {}))``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class CheckpointGateConfig(BaseModel):
    """Configurable checkpoint gates -- all off by default."""

    after_every_run: bool = False
    after_every_n_runs: int | None = None
    before_hardware_escalation: bool = False
    before_result_promotion: bool = False
    before_network_execution: bool = False


class AutonomyPolicy(BaseModel):
    """Cycle-level autonomy configuration.

    Defaults to supervised mode with no budget limits and all gates off.
    """

    mode: Literal["supervised", "autonomous"] = "supervised"
    max_total_runs: int | None = None
    max_wall_clock_hours: float | None = None
    max_runs_per_hypothesis: int | None = None
    max_wall_time_per_run_s: int | None = None
    summary_interval: int = 5
    checkpoint_gates: CheckpointGateConfig = CheckpointGateConfig()
    cost_budget_note: str = (
        "Phase 5 cost budgeting is deferred; only run-count and wall-clock "
        "limits are enforced."
    )
