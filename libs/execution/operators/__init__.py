"""Phase 3 execution operators -- register all with the worker executor."""

from __future__ import annotations

from collections.abc import Callable

from libs.core.operators import OperatorInput, OperatorResult

RegistrarFn = Callable[[str, Callable[[OperatorInput], OperatorResult]], None]


def register(register_operator: RegistrarFn) -> None:
    """Register all execution pipeline operators."""
    from libs.execution.operators.capture import execution_capture_operator
    from libs.execution.operators.run import execution_run_operator
    from libs.execution.operators.setup import execution_setup_operator

    register_operator("execution_setup", execution_setup_operator)
    register_operator("execution_run", execution_run_operator)
    register_operator("execution_capture", execution_capture_operator)
