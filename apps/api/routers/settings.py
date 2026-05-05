"""Runtime settings API."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.adapters.llm.router import ModelRouter
from libs.core.clock import utcnow
from libs.core.services.model_settings_service import (
    catalog_entry_to_role_config,
    load_model_config,
    yaml_role_defaults,
)
from libs.schemas.model_gateway import ModelRole
from libs.schemas.settings import (
    ModelCatalogEntryCreate,
    ModelCatalogEntryRead,
    ModelCatalogEntryUpdate,
    ModelCatalogTestResponse,
    ModelRoleBindingRead,
    ModelRoleBindingUpdate,
    ModelRoleDefaultRead,
    ModelSettingsResponse,
)
from libs.storage.models.settings import ModelCatalogEntry, ModelRoleBinding

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/settings", tags=["settings"])


def _catalog_read(entry: ModelCatalogEntry) -> ModelCatalogEntryRead:
    return ModelCatalogEntryRead.model_validate(entry)


def _binding_read(binding: ModelRoleBinding) -> ModelRoleBindingRead:
    return ModelRoleBindingRead.model_validate(binding)


def _yaml_default_read(cfg: dict[str, Any]) -> ModelRoleDefaultRead:
    return ModelRoleDefaultRead(
        provider=cfg["provider"],
        provider_type=cfg["provider_type"],
        model=cfg["model"],
        base_url=cfg.get("base_url"),
        temperature=cfg.get("temperature"),
        max_tokens=cfg.get("max_tokens"),
    )


def _validate_catalog_shape(
    provider_type: str,
    base_url: str | None,
) -> None:
    if provider_type == "openai_compatible" and not base_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="base_url is required for openai_compatible providers",
        )


async def _get_catalog_entry_or_404(
    db: AsyncSession,
    entry_id: uuid.UUID,
) -> ModelCatalogEntry:
    entry = await db.get(ModelCatalogEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Model catalog entry not found")
    return entry


@router.get(
    "/models",
    response_model=ModelSettingsResponse,
    dependencies=[Depends(require_scope("settings.read"))],
)
async def get_model_settings(
    db: AsyncSession = Depends(get_db),
) -> ModelSettingsResponse:
    entries = (
        await db.execute(select(ModelCatalogEntry).order_by(ModelCatalogEntry.display_name))
    ).scalars().all()
    bindings = (
        await db.execute(select(ModelRoleBinding).order_by(ModelRoleBinding.role))
    ).scalars().all()

    config = load_model_config()
    defaults = {
        role: _yaml_default_read(cfg)
        for role, cfg in yaml_role_defaults(config).items()
    }

    return ModelSettingsResponse(
        catalog_entries=[_catalog_read(entry) for entry in entries],
        roles=list(ModelRole),
        role_bindings=[_binding_read(binding) for binding in bindings],
        yaml_defaults=defaults,
    )


@router.post(
    "/models/catalog",
    response_model=ModelCatalogEntryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("settings.write"))],
)
async def create_catalog_entry(
    payload: ModelCatalogEntryCreate,
    db: AsyncSession = Depends(get_db),
) -> ModelCatalogEntryRead:
    existing = (
        await db.execute(
            select(ModelCatalogEntry).where(ModelCatalogEntry.key == payload.key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Catalog entry key already exists")

    entry = ModelCatalogEntry(
        id=uuid.uuid4(),
        key=payload.key,
        display_name=payload.display_name,
        provider_type=payload.provider_type,
        provider_name=payload.provider_name,
        model=payload.model,
        base_url=payload.base_url,
        default_temperature=payload.default_temperature,
        default_max_tokens=payload.default_max_tokens,
        enabled=payload.enabled,
        notes=payload.notes,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return _catalog_read(entry)


@router.patch(
    "/models/catalog/{entry_id}",
    response_model=ModelCatalogEntryRead,
    dependencies=[Depends(require_scope("settings.write"))],
)
async def update_catalog_entry(
    entry_id: uuid.UUID,
    payload: ModelCatalogEntryUpdate,
    db: AsyncSession = Depends(get_db),
) -> ModelCatalogEntryRead:
    entry = await _get_catalog_entry_or_404(db, entry_id)
    updates = payload.model_dump(exclude_unset=True)

    if "key" in updates:
        existing = (
            await db.execute(
                select(ModelCatalogEntry).where(
                    ModelCatalogEntry.key == updates["key"],
                    ModelCatalogEntry.id != entry.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Catalog entry key already exists")

    provider_type = updates.get("provider_type", entry.provider_type)
    base_url = updates.get("base_url", entry.base_url)
    _validate_catalog_shape(provider_type, base_url)

    if updates.get("enabled") is False and entry.enabled:
        bound_role = (
            await db.execute(
                select(ModelRoleBinding).where(
                    ModelRoleBinding.catalog_entry_id == entry.id
                )
            )
        ).scalar_one_or_none()
        if bound_role is not None:
            raise HTTPException(
                status_code=409,
                detail="Reassign roles before disabling this catalog entry",
            )

    for key, value in updates.items():
        setattr(entry, key, value)
    entry.updated_at = utcnow()
    await db.flush()
    await db.refresh(entry)
    return _catalog_read(entry)


@router.delete(
    "/models/catalog/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scope("settings.write"))],
)
async def delete_catalog_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    entry = await _get_catalog_entry_or_404(db, entry_id)
    bound_role = (
        await db.execute(
            select(ModelRoleBinding).where(ModelRoleBinding.catalog_entry_id == entry.id)
        )
    ).scalar_one_or_none()
    if bound_role is not None:
        raise HTTPException(
            status_code=409,
            detail="Reassign roles before deleting this catalog entry",
        )

    await db.delete(entry)
    await db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/models/roles/{role}",
    response_model=ModelRoleBindingRead,
    dependencies=[Depends(require_scope("settings.write"))],
)
async def assign_model_role(
    role: ModelRole,
    payload: ModelRoleBindingUpdate,
    db: AsyncSession = Depends(get_db),
) -> ModelRoleBindingRead:
    entry = await _get_catalog_entry_or_404(db, payload.catalog_entry_id)
    if not entry.enabled:
        raise HTTPException(status_code=422, detail="Disabled models cannot be assigned")
    _validate_catalog_shape(entry.provider_type, entry.base_url)

    binding = await db.get(ModelRoleBinding, role.value)
    if binding is None:
        binding = ModelRoleBinding(
            role=role.value,
            catalog_entry_id=payload.catalog_entry_id,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            updated_at=utcnow(),
        )
        db.add(binding)
    else:
        binding.catalog_entry_id = payload.catalog_entry_id
        binding.temperature = payload.temperature
        binding.max_tokens = payload.max_tokens
        binding.updated_at = utcnow()
    await db.flush()
    await db.refresh(binding)
    return _binding_read(binding)


@router.post(
    "/models/catalog/{entry_id}/test",
    response_model=ModelCatalogTestResponse,
    dependencies=[Depends(require_scope("settings.write"))],
)
async def test_catalog_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ModelCatalogTestResponse:
    entry = await _get_catalog_entry_or_404(db, entry_id)
    started = time.perf_counter()
    error: str | None = None
    success = False
    adapter = None

    try:
        cfg = catalog_entry_to_role_config(entry)
        adapter = ModelRouter()._build_adapter(cfg)
        await adapter.complete(
            [{"role": "user", "content": "Reply with OK."}],
            max_tokens=16,
        )
        success = True
    except Exception as exc:
        error = str(exc)[:2000]
    finally:
        if adapter is not None and hasattr(adapter, "close"):
            await adapter.close()

    latency_ms = int((time.perf_counter() - started) * 1000)
    entry.last_tested_at = utcnow()
    entry.last_test_ok = success
    entry.last_test_error = None if success else error
    entry.updated_at = utcnow()
    await db.flush()

    return ModelCatalogTestResponse(
        success=success,
        latency_ms=latency_ms,
        provider=entry.provider_name,
        model=entry.model,
        error=error,
    )
