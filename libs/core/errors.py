"""Operator error taxonomy and exception classification.

The worker uses :func:`classify_exception` to decide whether a failed job is
retried (transient), failed permanently, or marked cancelled/timed-out. Layers
that define their own exception types (e.g. the LLM adapter layer) register
them via :func:`register_transient` so core never imports adapter code.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar


class ErrorClass(StrEnum):
    """How the worker should treat a failed operator execution."""

    transient = "transient"  # infrastructure hiccup: retry with backoff
    permanent = "permanent"  # logic/input error: fail now, re-running won't help
    cancelled = "cancelled"  # user-requested cancel: mark cancelled, not failed
    timeout = "timeout"  # job deadline exceeded: retryable by default


class OperatorError(Exception):
    """Base class for typed operator failures. Defaults to permanent."""

    error_class: ClassVar[ErrorClass] = ErrorClass.permanent


class RetryableOperatorError(OperatorError):
    """Raise from an operator to opt a failure into job-level retry."""

    error_class = ErrorClass.transient


class PermanentOperatorError(OperatorError):
    """Explicitly non-retryable operator failure."""

    error_class = ErrorClass.permanent


class OperationCancelled(Exception):
    """Raised inside an operator when the job's cancel token trips."""


class OperatorTimeout(Exception):
    """Raised inside an operator when the job's wall-clock deadline trips."""


# Exception types registered as transient by other layers (e.g. LLM adapters
# register their transport errors at import time). Checked before the stdlib
# defaults so registrations can be more specific.
_REGISTERED_TRANSIENT: tuple[type[BaseException], ...] = ()

# Stdlib types that are near-always infrastructure failures. Deliberately
# narrow: OSError is excluded because FileNotFoundError/PermissionError are
# subclasses and re-running won't fix a missing file.
_STDLIB_TRANSIENT: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)


def register_transient(*exc_types: type[BaseException]) -> None:
    """Register exception types that classify as transient.

    Idempotent; intended to be called at import time by layers whose
    exceptions core must not import directly.
    """
    global _REGISTERED_TRANSIENT
    new = tuple(t for t in exc_types if t not in _REGISTERED_TRANSIENT)
    _REGISTERED_TRANSIENT = _REGISTERED_TRANSIENT + new


def _permanent_types() -> tuple[type[BaseException], ...]:
    # Imported lazily: state_machine imports are cheap but keep errors.py
    # importable from anywhere without cycles.
    from libs.core.state_machine import InvalidTransitionError

    permanent: list[type[BaseException]] = [
        InvalidTransitionError,
        ValueError,
        KeyError,
        TypeError,
    ]
    try:
        from pydantic import ValidationError

        permanent.append(ValidationError)
    except ImportError:  # pragma: no cover - pydantic is a hard dependency
        pass
    return tuple(permanent)


def classify_exception(exc: BaseException) -> ErrorClass:
    """Map an exception raised by an operator to an :class:`ErrorClass`.

    Unknown exception types classify as permanent: jobs here are hour-long
    LLM-heavy operations and blindly re-running a deterministic logic bug
    burns hardware time. Operators opt in to retry by raising
    :class:`RetryableOperatorError`, and infrastructure layers register
    their transient types via :func:`register_transient`.
    """
    if isinstance(exc, OperationCancelled):
        return ErrorClass.cancelled
    if isinstance(exc, OperatorTimeout):
        return ErrorClass.timeout
    if isinstance(exc, OperatorError):
        return exc.error_class
    if _REGISTERED_TRANSIENT and isinstance(exc, _REGISTERED_TRANSIENT):
        return ErrorClass.transient
    if isinstance(exc, _STDLIB_TRANSIENT):
        return ErrorClass.transient
    if isinstance(exc, _permanent_types()):
        return ErrorClass.permanent
    return ErrorClass.permanent
