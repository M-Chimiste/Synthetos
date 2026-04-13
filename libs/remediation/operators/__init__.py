"""Phase 4 operator registration."""

from __future__ import annotations

from collections.abc import Callable

from libs.core.operators import OperatorInput, OperatorResult

OperatorRegistrar = Callable[[str, Callable[[OperatorInput], OperatorResult]], None]


def register(register_operator: OperatorRegistrar) -> None:
    """Register all Phase 4 operators."""
    from libs.remediation.operators.recommend import recommend_operator
    from libs.remediation.operators.remediate import auto_remediate_operator
    from libs.remediation.operators.signal import signal_classify_operator

    register_operator("auto_remediate", auto_remediate_operator)
    register_operator("signal_classify", signal_classify_operator)
    register_operator("recommend", recommend_operator)
