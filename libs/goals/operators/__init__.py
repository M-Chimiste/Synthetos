"""Register goal-oriented research operators."""

from __future__ import annotations

from collections.abc import Callable

from libs.core.operators import OperatorInput, OperatorResult


def register(register_fn: Callable[[str, Callable[[OperatorInput], OperatorResult]], None]) -> None:
    from libs.goals.operators.advance import goal_advance_operator
    from libs.goals.operators.evaluate import goal_evaluate_operator, goal_report_operator

    register_fn("goal_advance", goal_advance_operator)
    register_fn("goal_evaluate", goal_evaluate_operator)
    register_fn("goal_report", goal_report_operator)
