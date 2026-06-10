"""Tests for the operator error taxonomy and exception classification."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from libs.core.errors import (
    ErrorClass,
    OperationCancelled,
    OperatorTimeout,
    PermanentOperatorError,
    RetryableOperatorError,
    classify_exception,
    register_transient,
)
from libs.core.state_machine import InvalidTransitionError
from libs.core.types import CycleStatus


class _Schema(BaseModel):
    value: int


def _validation_error() -> ValidationError:
    try:
        _Schema.model_validate({"value": "not-an-int-at-all"})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected validation error")


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (OperationCancelled("user cancel"), ErrorClass.cancelled),
        (OperatorTimeout("deadline"), ErrorClass.timeout),
        (RetryableOperatorError("flaky upstream"), ErrorClass.transient),
        (PermanentOperatorError("bad input"), ErrorClass.permanent),
        (ConnectionError("refused"), ErrorClass.transient),
        (ConnectionResetError("reset"), ErrorClass.transient),
        (TimeoutError("slow"), ErrorClass.transient),
        (
            InvalidTransitionError(CycleStatus.created, CycleStatus.closed),
            ErrorClass.permanent,
        ),
        (_validation_error(), ErrorClass.permanent),
        (ValueError("nope"), ErrorClass.permanent),
        (KeyError("missing"), ErrorClass.permanent),
        (TypeError("wrong"), ErrorClass.permanent),
        # FileNotFoundError is an OSError subclass but must NOT be transient.
        (FileNotFoundError("gone"), ErrorClass.permanent),
        # Unknown exception types default to permanent.
        (RuntimeError("mystery"), ErrorClass.permanent),
        (Exception("generic"), ErrorClass.permanent),
    ],
)
def test_classification_table(exc: BaseException, expected: ErrorClass) -> None:
    assert classify_exception(exc) == expected


def test_register_transient_extends_classification() -> None:
    class FlakyVendorError(Exception):
        pass

    assert classify_exception(FlakyVendorError("hiccup")) == ErrorClass.permanent
    register_transient(FlakyVendorError)
    assert classify_exception(FlakyVendorError("hiccup")) == ErrorClass.transient
    # Idempotent re-registration.
    register_transient(FlakyVendorError)
    assert classify_exception(FlakyVendorError("hiccup")) == ErrorClass.transient


def test_registered_transient_beats_permanent_default() -> None:
    class VendorValueError(ValueError):
        pass

    register_transient(VendorValueError)
    assert classify_exception(VendorValueError("retry me")) == ErrorClass.transient
    # Plain ValueError stays permanent.
    assert classify_exception(ValueError("nope")) == ErrorClass.permanent
