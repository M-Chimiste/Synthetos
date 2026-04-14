"""Phase 5 Pydantic schemas for autonomy policy, budget, and loop decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Autonomy policy
# ---------------------------------------------------------------------------


class CheckpointGateConfigRead(BaseModel):
    after_every_run: bool = False
    after_every_n_runs: int | None = None
    before_hardware_escalation: bool = False
    before_result_promotion: bool = False
    before_network_execution: bool = False


class AutonomyPolicyRead(BaseModel):
    mode: Literal["supervised", "autonomous"] = "supervised"
    max_total_runs: int | None = None
    max_wall_clock_hours: float | None = None
    max_runs_per_hypothesis: int | None = None
    max_wall_time_per_run_s: int | None = None
    summary_interval: int = 5
    checkpoint_gates: CheckpointGateConfigRead = CheckpointGateConfigRead()
    cost_budget_note: str = (
        "Phase 5 cost budgeting is deferred; only run-count and wall-clock limits are enforced."
    )


class AutonomyPolicyUpdate(BaseModel):
    """Update model -- all fields optional for partial updates."""

    mode: Literal["supervised", "autonomous"] | None = None
    max_total_runs: int | None = None
    max_wall_clock_hours: float | None = None
    max_runs_per_hypothesis: int | None = None
    max_wall_time_per_run_s: int | None = None
    summary_interval: int | None = None
    checkpoint_gates: CheckpointGateConfigRead | None = None


class AutonomyReportResponse(BaseModel):
    model_config = {"populate_by_name": True}

    cycle_id: UUID
    markdown: str | None = None
    json_payload: dict[str, Any] | None = Field(default=None, alias="json")


# ---------------------------------------------------------------------------
# Autonomy budget
# ---------------------------------------------------------------------------


class AutonomyBudgetRead(BaseModel):
    """Read model for autonomy budget consumption."""

    model_config = {"from_attributes": True}

    id: UUID
    cycle_id: UUID
    total_runs: int
    wall_clock_elapsed_s: float
    runs_per_hypothesis: dict[str, Any]
    started_at: datetime
    last_run_completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Loop decision
# ---------------------------------------------------------------------------


class LoopDecisionRead(BaseModel):
    """Read model for a loop decision."""

    model_config = {"from_attributes": True}

    id: UUID
    cycle_id: UUID
    charter_id: UUID
    run_record_id: UUID
    recommendation_id: UUID
    iteration_number: int
    decision: str
    gate_triggered: str | None = None
    budget_snapshot: dict[str, Any]
    hypothesis_card_id: UUID | None = None
    next_hypothesis_card_id: UUID | None = None
    next_action: str | None = None
    context_summary_path: str | None = None
    reasoning: str
    created_at: datetime
