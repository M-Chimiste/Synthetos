"""Authentication and scope guard tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from uuid_utils import uuid7

import apps.api.auth as auth
from apps.api.deps import get_db, get_settings
from apps.api.routers import remediation
from libs.core.config import Settings
from libs.storage.models.orchestrator import ApiToken, OrchestratorClient


def _request_with_auth(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )


def _token_record(
    *,
    scopes: list[str],
    enabled: bool = True,
    expires_at: datetime | None = None,
) -> ApiToken:
    client = OrchestratorClient(
        id=uuid7(),
        name="local-test-client",
        description="",
        enabled=enabled,
        created_at=datetime.now(UTC),
    )
    return ApiToken(
        id=uuid7(),
        client_id=client.id,
        token_hash="hash",
        scopes=scopes,
        created_at=datetime.now(UTC),
        expires_at=expires_at,
        revoked=False,
        client=client,
    )


@pytest.mark.asyncio
async def test_current_token_record_bypasses_auth_in_dev() -> None:
    request = Request({"type": "http", "headers": []})
    record = await auth._current_token_record(
        request,
        settings=Settings(env="dev"),
        db=object(),
    )
    assert record is None


@pytest.mark.asyncio
async def test_current_token_record_rejects_missing_header_in_prod() -> None:
    request = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException, match="Authorization header"):
        await auth._current_token_record(
            request,
            settings=Settings(env="prod"),
            db=object(),
        )


@pytest.mark.asyncio
async def test_current_token_record_validates_expiry_and_client_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_record = _token_record(
        scopes=["charters.read"],
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async def fake_get_token_record(_token: str, _db: object) -> ApiToken:
        return expired_record

    monkeypatch.setattr(auth, "_get_token_record", fake_get_token_record)

    with pytest.raises(HTTPException, match="Expired API token"):
        await auth._current_token_record(
            _request_with_auth("test-token"),
            settings=Settings(env="prod"),
            db=object(),
        )


@pytest.mark.asyncio
async def test_require_scope_allows_matching_scope() -> None:
    checker = auth.require_scope("events.read")
    await checker(
        settings=Settings(env="prod"),
        token_record=_token_record(scopes=["events.read"]),
    )


@pytest.mark.asyncio
async def test_require_scope_allows_admin_scope() -> None:
    checker = auth.require_scope("skills.bind")
    await checker(
        settings=Settings(env="prod"),
        token_record=_token_record(scopes=["admin.local"]),
    )


@pytest.mark.asyncio
async def test_require_scope_rejects_missing_scope() -> None:
    checker = auth.require_scope("runs.control")
    with pytest.raises(HTTPException, match="Missing required scope"):
        await checker(
            settings=Settings(env="prod"),
            token_record=_token_record(scopes=["runs.read"]),
        )


class _AsyncScalarResult:
    def __init__(self, value: Any):
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> _AsyncScalarResult:
        return self

    def all(self) -> Any:
        return self._value


class _AsyncReadSession:
    async def execute(self, _query: Any) -> _AsyncScalarResult:
        return _AsyncScalarResult(None)


@pytest.mark.parametrize(
    ("token", "scopes", "expected_status"),
    [
        ("allowed-token", ["cycles.read"], 200),
        ("denied-token", ["runs.read"], 403),
    ],
)
def test_remediation_routes_require_cycles_read_scope(
    monkeypatch: pytest.MonkeyPatch,
    token: str,
    scopes: list[str],
    expected_status: int,
) -> None:
    app = FastAPI()
    app.include_router(remediation.router, prefix="/api/v1")

    async def override_db():
        yield _AsyncReadSession()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(env="prod")

    async def fake_get_token_record(raw_token: str, _db: object) -> ApiToken | None:
        if raw_token != token:
            return None
        return _token_record(scopes=scopes)

    monkeypatch.setattr(auth, "_get_token_record", fake_get_token_record)

    client = TestClient(app)
    run_id = uuid7()
    response = client.get(
        f"/api/v1/runs/{run_id}/signal",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == expected_status
