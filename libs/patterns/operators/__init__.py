"""Phase 6 pattern operators.

Registers consolidate_patterns and decay_patterns with the worker executor.
"""

from __future__ import annotations

from collections.abc import Callable

from libs.core.operators import OperatorInput, OperatorResult


def register(
    register_fn: Callable[[str, Callable[[OperatorInput], OperatorResult]], None],
) -> None:
    """Register all Phase 6 pattern operators."""
    from libs.patterns.operators.consolidate import consolidate_patterns_operator
    from libs.patterns.operators.decay import decay_patterns_operator

    register_fn("consolidate_patterns", consolidate_patterns_operator)
    register_fn("decay_patterns", decay_patterns_operator)
