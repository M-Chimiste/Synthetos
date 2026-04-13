"""Phase 3 verification operators -- register all with the worker executor."""

from __future__ import annotations

from collections.abc import Callable

from libs.core.operators import OperatorInput, OperatorResult

RegistrarFn = Callable[[str, Callable[[OperatorInput], OperatorResult]], None]


def register(register_operator: RegistrarFn) -> None:
    """Register all verification pipeline operators."""
    from libs.verification.operators.check import verification_check_operator
    from libs.verification.operators.postmortem import verification_postmortem_operator

    register_operator("verification_check", verification_check_operator)
    register_operator("verification_postmortem", verification_postmortem_operator)
