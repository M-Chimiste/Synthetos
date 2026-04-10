"""Stub authentication and scope checking for Phase 0.

In development mode (LAB_ENV=dev, the default), all requests are
permitted without credentials.  When running in production the
middleware expects a ``Bearer <token>`` header whose value is looked
up in the ``api_tokens`` table (to be implemented in a later phase).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status

from apps.api.deps import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from libs.core.config import Settings


async def _current_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str | None:
    """Extract and validate the bearer token.

    In dev mode this always returns None (auth bypassed).
    """
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

    # TODO (Phase 2+): look up token in api_tokens table and verify scopes
    return token


def require_scope(scope: str) -> Callable:
    """Return a FastAPI dependency that asserts the caller has *scope*.

    In dev mode the check is skipped entirely.
    """

    async def _check(
        settings: Settings = Depends(get_settings),
        token: str | None = Depends(_current_token),
    ) -> None:
        if settings.env == "dev":
            return

        # TODO (Phase 2+): query api_tokens for this token's scopes and
        # raise 403 if *scope* is not present.
        _ = scope, token

    return _check
