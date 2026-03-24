"""Budget checking and tracking for autonomous experiment loops."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from libs.storage.models import (
        ResearchCharterModel,
        ResearchCycleModel,
        RunRecordModel,
    )


@dataclass
class BudgetStatus:
    """Result of checking all budget dimensions for a cycle."""

    within_budget: bool
    reason: str | None = None
    remaining_runs: int | None = None
    remaining_compute_minutes: float | None = None
    remaining_wall_clock_hours: float | None = None
    hypothesis_runs_remaining: int | None = None


def check_budget(
    cycle: ResearchCycleModel,
    hypothesis_public_id: str | None = None,
) -> BudgetStatus:
    """Check all budget dimensions. Returns within_budget=False if any limit hit."""
    # Total runs
    if cycle.budget_max_total_runs is not None:
        remaining = cycle.budget_max_total_runs - cycle.budget_used_run_count
        if remaining <= 0:
            return BudgetStatus(
                within_budget=False,
                reason=(
                    f"Total run budget exhausted: "
                    f"{cycle.budget_used_run_count}"
                    f"/{cycle.budget_max_total_runs}"
                ),
                remaining_runs=0,
            )

    # Compute minutes
    if cycle.budget_max_compute_minutes is not None:
        remaining_compute = (
            cycle.budget_max_compute_minutes
            - cycle.budget_used_compute_minutes
        )
        if remaining_compute <= 0:
            return BudgetStatus(
                within_budget=False,
                reason=(
                    f"Compute budget exhausted: "
                    f"{cycle.budget_used_compute_minutes:.1f}"
                    f"/{cycle.budget_max_compute_minutes} minutes"
                ),
                remaining_compute_minutes=0.0,
            )

    # Wall clock hours
    if cycle.budget_max_wall_clock_hours is not None:
        elapsed_hours = (
            datetime.now(UTC) - cycle.created_at
        ).total_seconds() / 3600
        remaining_wall = (
            cycle.budget_max_wall_clock_hours - elapsed_hours
        )
        if remaining_wall <= 0:
            return BudgetStatus(
                within_budget=False,
                reason=(
                    f"Wall clock budget exhausted: "
                    f"{elapsed_hours:.1f}"
                    f"/{cycle.budget_max_wall_clock_hours} hours"
                ),
                remaining_wall_clock_hours=0.0,
            )

    # Per-hypothesis runs
    hyp_remaining: int | None = None
    if (
        hypothesis_public_id is not None
        and cycle.budget_max_runs_per_hypothesis is not None
    ):
        hyp_runs = (cycle.budget_runs_per_hypothesis or {}).get(
            hypothesis_public_id, 0,
        )
        hyp_remaining = cycle.budget_max_runs_per_hypothesis - hyp_runs
        if hyp_remaining <= 0:
            return BudgetStatus(
                within_budget=False,
                reason=(
                    f"Per-hypothesis run budget exhausted for "
                    f"{hypothesis_public_id}: "
                    f"{hyp_runs}/{cycle.budget_max_runs_per_hypothesis}"
                ),
                hypothesis_runs_remaining=0,
            )

    # Compute remaining values for the status
    remaining_runs = None
    if cycle.budget_max_total_runs is not None:
        remaining_runs = (
            cycle.budget_max_total_runs - cycle.budget_used_run_count
        )

    remaining_compute = None
    if cycle.budget_max_compute_minutes is not None:
        remaining_compute = (
            cycle.budget_max_compute_minutes
            - cycle.budget_used_compute_minutes
        )

    remaining_wall = None
    if cycle.budget_max_wall_clock_hours is not None:
        elapsed = (
            datetime.now(UTC) - cycle.created_at
        ).total_seconds() / 3600
        remaining_wall = cycle.budget_max_wall_clock_hours - elapsed

    return BudgetStatus(
        within_budget=True,
        remaining_runs=remaining_runs,
        remaining_compute_minutes=remaining_compute,
        remaining_wall_clock_hours=remaining_wall,
        hypothesis_runs_remaining=hyp_remaining,
    )


def record_run_usage(
    session: Session,
    cycle: ResearchCycleModel,
    run: RunRecordModel,
    hypothesis_public_id: str,
) -> None:
    """Update budget tracking fields after a run completes."""
    # Compute time from started_at to completed_at
    if run.started_at and run.completed_at:
        elapsed_minutes = (
            run.completed_at - run.started_at
        ).total_seconds() / 60
        cycle.budget_used_compute_minutes = (
            (cycle.budget_used_compute_minutes or 0.0) + elapsed_minutes
        )

    # Increment run count
    cycle.budget_used_run_count = (cycle.budget_used_run_count or 0) + 1

    # Increment per-hypothesis count
    per_hyp = dict(cycle.budget_runs_per_hypothesis or {})
    per_hyp[hypothesis_public_id] = per_hyp.get(hypothesis_public_id, 0) + 1
    cycle.budget_runs_per_hypothesis = per_hyp


def copy_budget_from_charter(
    charter: ResearchCharterModel,
    cycle: ResearchCycleModel,
) -> None:
    """Copy budget_envelope from charter to cycle budget fields."""
    envelope = charter.budget_envelope or {}
    if "max_compute_minutes" in envelope:
        cycle.budget_max_compute_minutes = envelope["max_compute_minutes"]
    if "max_compute_hours" in envelope:
        cycle.budget_max_compute_minutes = (
            int(envelope["max_compute_hours"] * 60)
        )
    if "max_total_runs" in envelope:
        cycle.budget_max_total_runs = envelope["max_total_runs"]
    if "max_wall_clock_hours" in envelope:
        cycle.budget_max_wall_clock_hours = envelope["max_wall_clock_hours"]
    if "max_runs_per_hypothesis" in envelope:
        cycle.budget_max_runs_per_hypothesis = envelope[
            "max_runs_per_hypothesis"
        ]
