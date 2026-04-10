"""Pydantic schemas for ResearchCharter CRUD operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from libs.core.types import CharterStatus


class CharterCreate(BaseModel):
    """Schema for creating a new research charter."""

    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    problem_statement: str = ""
    source_scope: dict[str, Any] | None = None


class CharterUpdate(BaseModel):
    """Schema for updating an existing charter."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    problem_statement: str | None = None
    source_scope: dict[str, Any] | None = None
    status: CharterStatus | None = None


class CharterRead(BaseModel):
    """Schema for reading a charter."""

    model_config = {"from_attributes": True}

    id: UUID
    title: str
    description: str
    problem_statement: str
    source_scope: dict[str, Any] | None
    status: CharterStatus
    created_at: datetime
    updated_at: datetime
