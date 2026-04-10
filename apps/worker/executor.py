"""Job dispatcher -- maps job_type strings to operator handler functions."""

from __future__ import annotations

from collections.abc import Callable

from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult

log = get_logger("worker.executor")

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
        msg = f"Handler for {op_input.job_type!r} raised: {exc}"
        log.exception(msg, job_id=str(op_input.job_id), job_type=op_input.job_type)
        return OperatorResult(success=False, error=msg)

    return result
