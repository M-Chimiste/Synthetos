"""Phase 3 protocol operators -- register all with the worker executor."""

from __future__ import annotations

from collections.abc import Callable

from libs.core.operators import OperatorInput, OperatorResult

RegistrarFn = Callable[[str, Callable[[OperatorInput], OperatorResult]], None]


def register(register_operator: RegistrarFn) -> None:
    """Register all protocol pipeline operators."""
    from libs.protocols.operators.compile import protocol_compile_operator

    register_operator("protocol_compile", protocol_compile_operator)
