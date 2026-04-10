"""Health-check endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from sqlalchemy import text

from apps.api.deps import get_db
from libs.schemas.common import HealthResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return basic health status."""
    return HealthResponse()


@router.get("/ready", response_model=HealthResponse)
async def ready(
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    """Return readiness status after a simple database probe."""
    await db.execute(text("SELECT 1"))
    return HealthResponse()
