"""Health-check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from libs.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return basic health status."""
    return HealthResponse()
