"""Schemas for runtime settings."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from libs.schemas.model_gateway import ModelRole

ProviderType = Literal["anthropic", "openai", "google", "openai_compatible"]


class ModelCatalogEntryCreate(BaseModel):
    """Create a new model catalog entry."""

    key: str = Field(..., max_length=200)
    display_name: str = Field(..., max_length=300)
    provider_type: ProviderType
    provider_name: str = Field(..., max_length=100)
    model: str = Field(..., max_length=300)
    base_url: str | None = Field(default=None, max_length=500)
    default_temperature: float | None = Field(default=None, ge=0, le=2)
    default_max_tokens: int | None = Field(default=None, ge=1)
    enabled: bool = True
    notes: str | None = None

    @model_validator(mode="after")
    def validate_base_url(self) -> ModelCatalogEntryCreate:
        if self.provider_type == "openai_compatible" and not self.base_url:
            raise ValueError("base_url is required for openai_compatible providers")
        return self


class ModelCatalogEntryUpdate(BaseModel):
    """Patch mutable fields for a model catalog entry."""

    key: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=300)
    provider_type: ProviderType | None = None
    provider_name: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=300)
    base_url: str | None = Field(default=None, max_length=500)
    default_temperature: float | None = Field(default=None, ge=0, le=2)
    default_max_tokens: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
    notes: str | None = None


class ModelCatalogEntryRead(BaseModel):
    """Catalog entry returned to the UI."""

    id: UUID
    key: str
    display_name: str
    provider_type: ProviderType
    provider_name: str
    model: str
    base_url: str | None
    default_temperature: float | None
    default_max_tokens: int | None
    enabled: bool
    notes: str | None
    last_tested_at: datetime | None
    last_test_ok: bool | None
    last_test_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ModelRoleBindingUpdate(BaseModel):
    """Assign a catalog entry to a role with optional generation overrides."""

    catalog_entry_id: UUID
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)


class ModelRoleBindingRead(BaseModel):
    """Role binding returned to the UI."""

    role: ModelRole
    catalog_entry_id: UUID
    temperature: float | None
    max_tokens: int | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ModelRoleDefaultRead(BaseModel):
    """YAML fallback configuration for a role."""

    provider: str
    provider_type: ProviderType
    model: str
    base_url: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class ModelSettingsResponse(BaseModel):
    """Complete settings payload used by the Settings page."""

    catalog_entries: list[ModelCatalogEntryRead]
    roles: list[ModelRole]
    role_bindings: list[ModelRoleBindingRead]
    yaml_defaults: dict[ModelRole, ModelRoleDefaultRead]


class ModelCatalogTestResponse(BaseModel):
    """Result from a tiny completion test."""

    success: bool
    latency_ms: int
    provider: str
    model: str
    error: str | None = None
