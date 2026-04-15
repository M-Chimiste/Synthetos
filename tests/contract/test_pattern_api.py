"""Pattern API contract tests for the Phase 6 public surface."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import routing
from fastapi.testclient import TestClient

from apps.api.deps import get_db
from apps.api.main import create_app


class _NullSession:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("pattern contract tests must not execute SQL unexpectedly")

    async def commit(self) -> None:
        raise AssertionError("pattern contract tests must not commit")

    async def rollback(self) -> None:
        return None

    async def get(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def flush(self) -> None:
        return None

    def add(self, _obj: Any) -> None:
        raise AssertionError("pattern contract tests must not write")

    async def run_sync(self, fn, *args, **kwargs):
        return fn(object(), *args, **kwargs)


async def _null_db() -> AsyncGenerator[_NullSession]:
    yield _NullSession()


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = _null_db
    return TestClient(app)


def test_openapi_exposes_pattern_routes() -> None:
    app = create_app()
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    paths = schema.get("paths", {})
    expected = {
        "/api/v1/patterns",
        "/api/v1/patterns/consolidate",
        "/api/v1/patterns/decay",
        "/api/v1/patterns/retrieve-preview",
        "/api/v1/patterns/{pattern_id}",
        "/api/v1/patterns/{pattern_id}/observations",
        "/api/v1/patterns/{pattern_id}/approve",
        "/api/v1/patterns/{pattern_id}/reject",
        "/api/v1/patterns/{pattern_id}/trust-tier",
        "/api/v1/patterns/{pattern_id}/retrieve-preview",
    }
    assert expected.issubset(paths.keys())


def test_pattern_retrieve_preview_route_requires_charter_id(client: TestClient) -> None:
    resp = client.post(f"/api/v1/patterns/{uuid4()}/retrieve-preview", json={})
    assert resp.status_code == 422


def test_pattern_retrieve_preview_route_404s_for_missing_pattern(client: TestClient) -> None:
    resp = client.post(
        f"/api/v1/patterns/{uuid4()}/retrieve-preview",
        json={"charter_id": str(uuid4())},
    )
    assert resp.status_code == 404


def test_pattern_routes_use_expected_scopes() -> None:
    app = create_app()
    expected_scopes = {
        ("GET", "/api/v1/patterns"): "patterns.read",
        ("GET", "/api/v1/patterns/{pattern_id}"): "patterns.read",
        ("GET", "/api/v1/patterns/{pattern_id}/observations"): "patterns.read",
        ("POST", "/api/v1/patterns/retrieve-preview"): "patterns.read",
        ("POST", "/api/v1/patterns/{pattern_id}/retrieve-preview"): "patterns.read",
        ("POST", "/api/v1/patterns/consolidate"): "patterns.write",
        ("POST", "/api/v1/patterns/decay"): "patterns.write",
        ("POST", "/api/v1/patterns/{pattern_id}/approve"): "patterns.write",
        ("POST", "/api/v1/patterns/{pattern_id}/reject"): "patterns.write",
        ("PATCH", "/api/v1/patterns/{pattern_id}/trust-tier"): "patterns.write",
    }
    seen: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, routing.APIRoute):
            continue
        for method in route.methods or set():
            key = (method, route.path)
            if key not in expected_scopes:
                continue
            seen.add(key)
            assert _route_uses_scope(route, expected_scopes[key]), (
                f"{method} {route.path} missing scope {expected_scopes[key]}"
            )
    assert seen == set(expected_scopes)


def _route_uses_scope(route: routing.APIRoute, scope: str) -> bool:
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        if call is not None:
            cells = getattr(call, "__closure__", None) or ()
            for cell in cells:
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if value == scope:
                    return True
        stack.extend(dep.dependencies)
    return False
