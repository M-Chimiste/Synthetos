"""Goal evaluation and reporting operators."""

from __future__ import annotations

from uuid import UUID

from libs.core.operators import OperatorInput, OperatorResult
from libs.core.services.goal_service import (
    GoalServiceError,
    evaluate_goal_attempt_sync,
    write_goal_report,
)
from libs.storage.base import get_sync_session_factory
from libs.storage.models.goals import ResearchGoal


def goal_evaluate_operator(op_input: OperatorInput) -> OperatorResult:
    goal_id_raw = op_input.payload.get("goal_id")
    cycle_id_raw = op_input.payload.get("cycle_id")
    if goal_id_raw is None or cycle_id_raw is None:
        return OperatorResult(success=False, error="goal_evaluate missing goal_id or cycle_id")

    try:
        goal_id = UUID(str(goal_id_raw))
        cycle_id = UUID(str(cycle_id_raw))
    except ValueError as exc:
        return OperatorResult(success=False, error=f"invalid goal_evaluate payload: {exc}")

    artifacts = [str(p) for p in op_input.payload.get("artifacts") or []]
    factory = get_sync_session_factory()
    try:
        with factory() as db:
            goal, attempt, result = evaluate_goal_attempt_sync(
                db,
                goal_id=goal_id,
                cycle_id=cycle_id,
                cycle_report_paths=artifacts,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary=(
                    f"Goal {goal.id} attempt {attempt.attempt_number}: "
                    f"{result['next_action']}"
                ),
                artifacts=[p for p in [goal.report_path, goal.report_json_path] if p],
            )
    except GoalServiceError as exc:
        return OperatorResult(success=False, error=str(exc))


def goal_report_operator(op_input: OperatorInput) -> OperatorResult:
    goal_id_raw = op_input.payload.get("goal_id")
    if goal_id_raw is None:
        return OperatorResult(success=False, error="goal_report missing goal_id")
    try:
        goal_id = UUID(str(goal_id_raw))
    except ValueError as exc:
        return OperatorResult(success=False, error=f"invalid goal_id: {exc}")

    factory = get_sync_session_factory()
    with factory() as db:
        goal = db.get(ResearchGoal, goal_id)
        if goal is None:
            return OperatorResult(success=False, error=f"goal {goal_id} not found")
        paths = write_goal_report(db, goal)
        goal.report_path = paths["markdown"]
        goal.report_json_path = paths["json"]
        db.commit()
    return OperatorResult(
        success=True,
        summary=f"Goal report generated for {goal_id}",
        artifacts=[paths["markdown"], paths["json"]],
    )
