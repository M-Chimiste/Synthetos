"""Token authentication and scope checking for the Phase 0 API surface."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from apps.api.deps import get_db, get_settings
from libs.core.clock import utcnow

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from libs.core.config import Settings
    from libs.storage.models.orchestrator import ApiToken


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _get_token_record(
    token: str,
    db: AsyncSession,
) -> ApiToken | None:
    from libs.storage.models.orchestrator import ApiToken

    token_digest = _token_hash(token)
    result = await db.execute(
        select(ApiToken)
        .options(selectinload(ApiToken.client))
        .where(ApiToken.token_hash == token_digest, ApiToken.revoked.is_(False))
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None
    if not hmac.compare_digest(record.token_hash, token_digest):
        return None
    return record


def _is_expired(expires_at: datetime | None) -> bool:
    return expires_at is not None and expires_at <= utcnow()


async def _current_token_record(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> ApiToken | None:
    """Extract and validate the bearer token, returning its DB record."""
    if settings.env == "dev":
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty bearer token",
        )

    token_record = await _get_token_record(token, db)
    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown API token",
        )

    if _is_expired(token_record.expires_at):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expired API token",
        )

    if not token_record.client.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Disabled orchestrator client",
        )

    return token_record


def require_scope(scope: str) -> Callable:
    """Return a FastAPI dependency that asserts the caller has *scope*.

    In dev mode the check is skipped entirely.
    """

    async def _check(
        settings: Settings = Depends(get_settings),
        token_record: ApiToken | None = Depends(_current_token_record),
    ) -> None:
        if settings.env == "dev":
            return

        if token_record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API token",
            )

        if token_record.revoked or _is_expired(token_record.expires_at):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API token",
            )

        scopes = set(token_record.scopes)
        if "admin.local" in scopes or scope in scopes:
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope '{scope}'",
        )

    return _check
