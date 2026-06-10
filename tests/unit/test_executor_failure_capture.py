"""Tests for executor traceback capture and error classification."""

from __future__ import annotations

from uuid import UUID

from uuid_utils import uuid7

from apps.worker.executor import execute, register_operator
from libs.core.errors import ErrorClass, OperationCancelled, RetryableOperatorError
from libs.core.operators import OperatorInput


def _op_input(job_type: str) -> OperatorInput:
    return OperatorInput(
        cycle_id=UUID(int=0),
        charter_id=UUID(int=0),
        job_id=uuid7(),
        job_type=job_type,
        payload={},
    )


def test_raising_handler_captures_failure_detail() -> None:
    def _boom(_op_input: OperatorInput):
        raise ValueError("bad hypothesis payload")

    register_operator("test_boom_permanent", _boom)
    result = execute(_op_input("test_boom_permanent"))

    assert result.success is False
    assert result.error == "ValueError: bad hypothesis payload"
    assert result.failure is not None
    assert result.failure.error_class == ErrorClass.permanent
    assert result.failure.exc_type == "ValueError"
    assert result.failure.traceback is not None
    assert "bad hypothesis payload" in result.failure.traceback
    assert "Traceback" in result.failure.traceback


def test_retryable_error_classified_transient() -> None:
    def _flaky(_op_input: OperatorInput):
        raise RetryableOperatorError("upstream flake")

    register_operator("test_boom_transient", _flaky)
    result = execute(_op_input("test_boom_transient"))

    assert result.success is False
    assert result.failure is not None
    assert result.failure.error_class == ErrorClass.transient


def test_cancellation_classified_cancelled() -> None:
    def _cancelled(_op_input: OperatorInput):
        raise OperationCancelled("user hit the kill switch")

    register_operator("test_boom_cancelled", _cancelled)
    result = execute(_op_input("test_boom_cancelled"))

    assert result.success is False
    assert result.failure is not None
    assert result.failure.error_class == ErrorClass.cancelled


def test_unregistered_job_type_has_no_failure_detail() -> None:
    result = execute(_op_input("test_never_registered"))
    assert result.success is False
    assert result.failure is None  # treated as permanent by the worker


def test_long_traceback_is_truncated() -> None:
    def _deep(_op_input: OperatorInput):
        def recurse(n: int) -> None:
            if n == 0:
                raise RuntimeError("x" * 30_000)
            recurse(n - 1)

        recurse(400)

    register_operator("test_boom_deep", _deep)
    result = execute(_op_input("test_boom_deep"))

    assert result.failure is not None
    assert result.failure.traceback is not None
    assert len(result.failure.traceback) <= 20_100
    assert result.failure.traceback.startswith("[... traceback truncated ...]")
