"""Schemas for goal-oriented research mode."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

GoalStatusLiteral = Literal[
    "created",
    "running",
    "satisfied",
    "exhausted",
    "stopped",
    "failed",
]

GoalCriterionType = Literal[
    "completed_run_exists",
    "metric_present",
    "metric_threshold",
    "artifact_exists",
    "verification_passed",
    "report_generated",
]


class GoalCriterion(BaseModel):
    name: str
    description: str = ""
    required: bool = True
    check_type: GoalCriterionType
    params: dict[str, Any] = Field(default_factory=dict)
    scope: Literal["attempt", "cumulative"] = "cumulative"


class GoalPolicy(BaseModel):
    max_attempt_cycles: int = 5
    max_total_runs: int | None = None
    max_wall_clock_hours: float | None = None
    autonomy: dict[str, Any] = Field(default_factory=dict)
    discovery: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] = Field(default_factory=dict)
    hypothesis: dict[str, Any] = Field(default_factory=dict)
    protocol: dict[str, Any] = Field(default_factory=dict)
    repair: dict[str, Any] = Field(default_factory=dict)


GoalRepairAction = Literal["retry_stage", "start_next_attempt", "stop_failed"]


class GoalRepairPlan(BaseModel):
    diagnosis: str
    previous_attempts_considered: list[str] = Field(default_factory=list)
    proposed_action: GoalRepairAction
    change_summary: str
    expected_new_information: str
    anti_repeat_reason: str
    payload_patch: dict[str, Any] = Field(default_factory=dict)
    config_patch: dict[str, Any] = Field(default_factory=dict)


class GoalCreate(BaseModel):
    charter_id: UUID
    title: str
    goal_statement: str
    success_criteria: list[GoalCriterion]
    policy: GoalPolicy = GoalPolicy()


class GoalRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    charter_id: UUID
    title: str
    goal_statement: str
    success_criteria: list[dict[str, Any]]
    policy: dict[str, Any]
    status: GoalStatusLiteral
    summary: str | None = None
    report_path: str | None = None
    report_json_path: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class GoalAttemptRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    goal_id: UUID
    charter_id: UUID
    cycle_id: UUID
    attempt_number: int
    status: str
    evaluation: dict[str, Any] | None = None
    report_path: str | None = None
    report_json_path: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class GoalReportResponse(BaseModel):
    model_config = {"populate_by_name": True}

    goal_id: UUID
    markdown: str | None = None
    json_payload: dict[str, Any] | None = Field(default=None, alias="json")
