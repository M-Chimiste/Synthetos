"""Shared Pydantic schemas for pagination, errors, and common patterns."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaginatedResponse[T](BaseModel):
    """Standard paginated response wrapper."""

    items: list[T]
    total: int
    offset: int = 0
    limit: int = 50


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    code: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "0.1.0"


class PaginationParams(BaseModel):
    """Query parameters for paginated endpoints."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
