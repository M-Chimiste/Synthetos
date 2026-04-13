"""Phase 3 hypothesis operators -- register all with the worker executor."""

from __future__ import annotations

from collections.abc import Callable

from libs.core.operators import OperatorInput, OperatorResult

RegistrarFn = Callable[[str, Callable[[OperatorInput], OperatorResult]], None]


def register(register_operator: RegistrarFn) -> None:
    """Register all hypothesis pipeline operators."""
    from libs.ideation.operators.critique import hypothesis_critique_operator
    from libs.ideation.operators.generate import hypothesis_generate_operator
    from libs.ideation.operators.rank import hypothesis_rank_operator

    register_operator("hypothesis_generate", hypothesis_generate_operator)
    register_operator("hypothesis_critique", hypothesis_critique_operator)
    register_operator("hypothesis_rank", hypothesis_rank_operator)
