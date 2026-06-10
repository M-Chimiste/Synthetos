"""Job dispatcher -- maps job_type strings to operator handler functions."""

from __future__ import annotations

import traceback
from collections.abc import Callable

from libs.core.errors import classify_exception
from libs.core.logging import get_logger
from libs.core.operators import OperatorFailure, OperatorInput, OperatorResult

log = get_logger("worker.executor")

_TRACEBACK_CAP_CHARS = 20_000

# ---------------------------------------------------------------------------
# Handler type: a callable that receives OperatorInput and returns OperatorResult
# ---------------------------------------------------------------------------
OperatorHandler = Callable[[OperatorInput], OperatorResult]

# ---------------------------------------------------------------------------
# Registry of job_type -> handler
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, OperatorHandler] = {}


def register_operator(job_type: str, handler: OperatorHandler) -> None:
    """Register a handler for a given job type."""
    _REGISTRY[job_type] = handler


def _echo_operator(op_input: OperatorInput) -> OperatorResult:
    """Placeholder operator that echoes the input payload back as the result."""
    return OperatorResult(
        success=True,
        summary=f"Echo operator returned payload for job {op_input.job_id}",
        state_patch={"echoed": op_input.payload},
    )


# Register built-in operators
register_operator("echo", _echo_operator)


def _register_discovery_operators() -> None:
    """Register the Phase 1 discovery operator chain."""
    from libs.discovery.operators import register as register_discovery

    register_discovery(register_operator)


_register_discovery_operators()


def _register_analysis_operators() -> None:
    """Register the Phase 2 analysis operator chain."""
    from libs.analysis.operators import register as register_analysis

    register_analysis(register_operator)


_register_analysis_operators()


def _register_ideation_operators() -> None:
    """Register the Phase 3 hypothesis operator chain."""
    from libs.ideation.operators import register as register_ideation

    register_ideation(register_operator)


_register_ideation_operators()


def _register_protocol_operators() -> None:
    """Register the Phase 3 protocol operator chain."""
    from libs.protocols.operators import register as register_protocols

    register_protocols(register_operator)


_register_protocol_operators()


def _register_execution_operators() -> None:
    """Register the Phase 3 execution operator chain."""
    from libs.execution.operators import register as register_execution

    register_execution(register_operator)


_register_execution_operators()


def _register_verification_operators() -> None:
    """Register the Phase 3 verification operator chain."""
    from libs.verification.operators import register as register_verification

    register_verification(register_operator)


_register_verification_operators()


def _register_remediation_operators() -> None:
    """Register the Phase 4 remediation, signal, and recommendation operators."""
    from libs.remediation.operators import register as register_remediation

    register_remediation(register_operator)


_register_remediation_operators()


def _register_autonomy_operators() -> None:
    """Register the Phase 5 autonomy operator chain."""
    from libs.autonomy.operators import register as register_autonomy

    register_autonomy(register_operator)


_register_autonomy_operators()


def _register_pattern_operators() -> None:
    """Register the Phase 6 canonical-pattern operators."""
    from libs.patterns.operators import register as register_patterns

    register_patterns(register_operator)


_register_pattern_operators()


def _register_goal_operators() -> None:
    """Register goal-oriented research operators."""
    from libs.goals.operators import register as register_goals

    register_goals(register_operator)


_register_goal_operators()


def execute(op_input: OperatorInput) -> OperatorResult:
    """Dispatch a job to its registered operator handler.

    If the handler raises, the exception is caught and an error
    OperatorResult is returned so the caller can mark the job as failed.
    """
    handler = _REGISTRY.get(op_input.job_type)
    if handler is None:
        msg = f"No handler registered for job_type={op_input.job_type!r}"
        log.error(msg, job_id=str(op_input.job_id), job_type=op_input.job_type)
        return OperatorResult(success=False, error=msg)

    try:
        result = handler(op_input)
    except Exception as exc:
        msg = f"{type(exc).__qualname__}: {exc}"
        log.exception(
            f"Handler for {op_input.job_type!r} raised",
            job_id=str(op_input.job_id),
            job_type=op_input.job_type,
        )
        return OperatorResult(
            success=False,
            error=msg,
            failure=OperatorFailure(
                error_class=classify_exception(exc),
                exc_type=type(exc).__qualname__,
                traceback=_truncate_traceback(traceback.format_exc()),
            ),
        )

    return result


def _truncate_traceback(tb: str) -> str:
    """Cap a traceback, keeping the tail (the raising frame matters most)."""
    if len(tb) <= _TRACEBACK_CAP_CHARS:
        return tb
    return "[... traceback truncated ...]\n" + tb[-_TRACEBACK_CAP_CHARS:]
