"""Goal advancement operator."""

from __future__ import annotations

from uuid import UUID

from libs.core.operators import OperatorInput, OperatorResult
from libs.core.services.goal_service import GoalServiceError, advance_goal_cycle_sync
from libs.storage.base import get_sync_session_factory


def goal_advance_operator(op_input: OperatorInput) -> OperatorResult:
    goal_id_raw = op_input.payload.get("goal_id")
    cycle_id_raw = op_input.payload.get("cycle_id") or op_input.cycle_id
    if goal_id_raw is None or cycle_id_raw is None:
        return OperatorResult(success=False, error="goal_advance missing goal_id or cycle_id")

    try:
        goal_id = UUID(str(goal_id_raw))
        cycle_id = UUID(str(cycle_id_raw))
    except ValueError as exc:
        return OperatorResult(success=False, error=f"invalid goal_advance payload: {exc}")

    trigger = str(op_input.payload.get("trigger") or "manual")
    failure = op_input.payload.get("failure")
    if failure is not None and not isinstance(failure, dict):
        return OperatorResult(success=False, error="goal_advance failure payload must be an object")

    factory = get_sync_session_factory()
    try:
        with factory() as db:
            result = advance_goal_cycle_sync(
                db,
                goal_id=goal_id,
                cycle_id=cycle_id,
                trigger=trigger,
                failure=failure,
            )
            db.commit()
            return OperatorResult(
                success=True,
                summary=f"Goal advance: {result.get('summary', result.get('next_action'))}",
            )
    except GoalServiceError as exc:
        return OperatorResult(success=False, error=str(exc))
