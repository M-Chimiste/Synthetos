"""FastAPI dependency injection providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from libs.core.config import get_settings as _get_settings
from libs.storage.base import get_async_session_factory

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession

    from libs.core.config import Settings


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield an async database session, committing on success."""
    factory = get_async_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_settings() -> Settings:
    """Return the singleton application settings."""
    return _get_settings()
