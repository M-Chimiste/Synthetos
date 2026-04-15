"""Phase 5 autonomy operators.

Registers loop_decide and loop_report with the worker executor.
"""

from __future__ import annotations

from collections.abc import Callable

from libs.core.operators import OperatorInput, OperatorResult


def register(
    register_fn: Callable[[str, Callable[[OperatorInput], OperatorResult]], None],
) -> None:
    """Register all Phase 5 autonomy operators."""
    from libs.autonomy.operators.loop_decide import loop_decide_operator
    from libs.autonomy.operators.loop_report import loop_report_operator

    register_fn("loop_decide", loop_decide_operator)
    register_fn("loop_report", loop_report_operator)
