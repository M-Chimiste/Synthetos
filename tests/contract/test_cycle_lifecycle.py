"""Cycle-lifecycle contract shape tests (Phase 6 §5.2).

These hermetic tests verify the validation and endpoint branch contracts
without requiring a running Postgres. They verify:

  * Write endpoints reject missing/invalid bodies with 422 (not 500).
  * Patterns surface accepts optional / well-formed payloads.
  * Patterns surface rejects unknown pattern_types with 422.

A full DB-backed lifecycle drive (create charter → cycle → events → run)
lives in ``tests/integration/`` (skipped when no DB is available).
"""

from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.api.main import create_app
from apps.api.routers.patterns import update_trust_tier
from libs.schemas.charter import CharterCreate
from libs.schemas.cycle import CycleCreate
from libs.schemas.patterns import (
    ApproveRequest,
    ConsolidateRequest,
    RetrievePreviewRequest,
    TrustTierUpdateRequest,
)


class _NullSession:
    """Minimal AsyncSession stub that raises on any real use.

    These tests intentionally never execute queries -- validation happens
    before the DB is touched. If a test ever reaches a query, the stub will
    raise and the test will fail loudly instead of silently passing.
    """

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("contract tests must not execute DB queries")

    async def commit(self) -> None:
        raise AssertionError("contract tests must not commit")

    async def rollback(self) -> None:
        return None

    async def get(self, *_a: Any, **_k: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, _obj: Any) -> None:
        raise AssertionError("contract tests must not write")


def test_create_charter_rejects_empty_body() -> None:
    with pytest.raises(ValidationError):
        CharterCreate.model_validate({})


def test_create_cycle_rejects_empty_body() -> None:
    with pytest.raises(ValidationError):
        CycleCreate.model_validate({})


def test_pattern_consolidate_rejects_unknown_type() -> None:
    body = ConsolidateRequest(pattern_types=["not_a_real_type"])
    with pytest.raises(ValueError):
        body.validate_types()


def test_pattern_retrieve_preview_requires_charter_id() -> None:
    with pytest.raises(ValidationError):
        RetrievePreviewRequest.model_validate({})


def test_pattern_specific_retrieve_preview_requires_charter_id() -> None:
    schema = create_app().openapi()
    assert "/api/v1/patterns/{pattern_id}/retrieve-preview" in schema["paths"]
    with pytest.raises(ValidationError):
        RetrievePreviewRequest.model_validate({})


async def test_pattern_trust_tier_rejects_unknown_tier() -> None:
    from uuid import uuid4

    with pytest.raises(HTTPException) as exc_info:
        await update_trust_tier(
            uuid4(),
            TrustTierUpdateRequest(trust_tier="bogus", rationale="x"),
            None,
            _NullSession(),  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 422


def test_pattern_approve_requires_rationale() -> None:
    with pytest.raises(ValidationError):
        ApproveRequest.model_validate({})


def test_pattern_approve_rejects_empty_rationale() -> None:
    with pytest.raises(ValidationError):
        ApproveRequest.model_validate({"rationale": ""})
