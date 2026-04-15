"""Budget tracking for the autonomous loop.

Tracks run count, wall-clock time, and per-hypothesis run counts.
Dollar-cost budgets are deferred to a future iteration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.storage.models.autonomy import AutonomyBudget

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from libs.autonomy.policy import AutonomyPolicy


@dataclass(frozen=True)
class BudgetCheckResult:
    """Result of checking budget limits."""

    exceeded: bool
    limit_name: str | None = None
    detail: str = ""


def load_or_create_budget(session: Session, cycle_id: UUID) -> AutonomyBudget:
    """Load the existing budget for a cycle, or create a fresh one."""
    budget = session.execute(
        select(AutonomyBudget).where(AutonomyBudget.cycle_id == cycle_id)
    ).scalar_one_or_none()
    if budget is not None:
        return budget

    budget = AutonomyBudget(
        id=uuid7(),
        cycle_id=cycle_id,
        total_runs=0,
        wall_clock_elapsed_s=0.0,
        runs_per_hypothesis={},
        started_at=utcnow(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(budget)
    session.flush()
    return budget


def increment_budget(
    session: Session,
    budget: AutonomyBudget,
    hypothesis_card_id: UUID,
) -> None:
    """Increment budget counters after a run completes."""
    now = utcnow()
    budget.total_runs += 1
    budget.last_run_completed_at = now
    budget.wall_clock_elapsed_s = (now - budget.started_at).total_seconds()
    budget.updated_at = now

    card_key = str(hypothesis_card_id)
    rph = dict(budget.runs_per_hypothesis or {})
    rph[card_key] = rph.get(card_key, 0) + 1
    budget.runs_per_hypothesis = rph

    session.flush()


def check_budget(policy: AutonomyPolicy, budget: AutonomyBudget) -> BudgetCheckResult:
    """Check whether any budget limit has been exceeded."""
    if policy.max_total_runs is not None and budget.total_runs >= policy.max_total_runs:
        return BudgetCheckResult(
            exceeded=True,
            limit_name="max_total_runs",
            detail=(
                f"Total runs ({budget.total_runs}) reached limit "
                f"({policy.max_total_runs})."
            ),
        )

    if policy.max_wall_clock_hours is not None:
        elapsed_hours = budget.wall_clock_elapsed_s / 3600.0
        if elapsed_hours >= policy.max_wall_clock_hours:
            return BudgetCheckResult(
                exceeded=True,
                limit_name="max_wall_clock_hours",
                detail=(
                    f"Wall-clock time ({elapsed_hours:.2f}h) reached limit "
                    f"({policy.max_wall_clock_hours}h)."
                ),
            )

    return BudgetCheckResult(exceeded=False)


def check_per_hypothesis_budget(
    policy: AutonomyPolicy,
    budget: AutonomyBudget,
    hypothesis_card_id: UUID,
) -> BudgetCheckResult:
    """Check per-hypothesis run limit for a specific card."""
    if policy.max_runs_per_hypothesis is None:
        return BudgetCheckResult(exceeded=False)

    card_key = str(hypothesis_card_id)
    count = (budget.runs_per_hypothesis or {}).get(card_key, 0)
    if count >= policy.max_runs_per_hypothesis:
        return BudgetCheckResult(
            exceeded=True,
            limit_name="max_runs_per_hypothesis",
            detail=(
                f"Hypothesis {card_key} has {count} runs, "
                f"limit is {policy.max_runs_per_hypothesis}."
            ),
        )

    return BudgetCheckResult(exceeded=False)
