"""Cycle-lifecycle contract shape tests (Phase 6 §5.2).

These hermetic tests override the DB dependency so the HTTP contract can be
exercised without a running Postgres. They verify:

  * Write endpoints reject missing/invalid bodies with 422 (not 500).
  * Patterns surface accepts optional / well-formed payloads.
  * Patterns surface rejects unknown pattern_types with 422.

A full DB-backed lifecycle drive (create charter → cycle → events → run)
lives in ``tests/integration/`` (skipped when no DB is available).
"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.deps import get_db
from apps.api.main import create_app


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


async def _null_db() -> AsyncGenerator[_NullSession]:
    yield _NullSession()


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _null_db
    return TestClient(app)


def test_create_charter_rejects_empty_body(client: TestClient) -> None:
    resp = client.post("/api/v1/charters", json={})
    assert resp.status_code == 422


def test_create_cycle_rejects_empty_body(client: TestClient) -> None:
    resp = client.post("/api/v1/cycles", json={})
    assert resp.status_code == 422


def test_pattern_consolidate_rejects_unknown_type(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/patterns/consolidate",
        json={"pattern_types": ["not_a_real_type"]},
    )
    assert resp.status_code == 422


def test_pattern_retrieve_preview_requires_charter_id(client: TestClient) -> None:
    resp = client.post("/api/v1/patterns/retrieve-preview", json={})
    assert resp.status_code == 422


def test_pattern_specific_retrieve_preview_requires_charter_id(client: TestClient) -> None:
    from uuid import uuid4

    resp = client.post(f"/api/v1/patterns/{uuid4()}/retrieve-preview", json={})
    assert resp.status_code == 422


def test_pattern_trust_tier_rejects_unknown_tier(client: TestClient) -> None:
    from uuid import uuid4

    resp = client.patch(
        f"/api/v1/patterns/{uuid4()}/trust-tier",
        json={"trust_tier": "bogus", "rationale": "x"},
    )
    assert resp.status_code == 422


def test_pattern_approve_requires_rationale(client: TestClient) -> None:
    from uuid import uuid4

    resp = client.post(
        f"/api/v1/patterns/{uuid4()}/approve",
        json={},
    )
    assert resp.status_code == 422


def test_pattern_approve_rejects_empty_rationale(client: TestClient) -> None:
    from uuid import uuid4

    resp = client.post(
        f"/api/v1/patterns/{uuid4()}/approve",
        json={"rationale": ""},
    )
    assert resp.status_code == 422
