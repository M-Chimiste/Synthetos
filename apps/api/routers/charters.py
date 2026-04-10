"""CRUD endpoints for research charters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.core.services.charter_service import (
    create_charter,
    get_charter,
    list_charters,
    update_charter,
)
from libs.schemas.charter import CharterCreate, CharterRead, CharterUpdate
from libs.schemas.common import PaginatedResponse

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/charters", tags=["charters"])


@router.post("", response_model=CharterRead, status_code=201)
async def create_charter_endpoint(
    body: CharterCreate,
    _: None = Depends(require_scope("charters.write")),
    db: AsyncSession = Depends(get_db),
) -> CharterRead:
    """Create a new research charter."""
    return await create_charter(db, body)


@router.get("", response_model=PaginatedResponse[CharterRead])
async def list_charters_endpoint(
    offset: int = 0,
    limit: int = 50,
    _: None = Depends(require_scope("charters.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CharterRead]:
    """List research charters with pagination."""
    items, total = await list_charters(db, offset=offset, limit=limit)
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{charter_id}", response_model=CharterRead)
async def get_charter_endpoint(
    charter_id: UUID,
    _: None = Depends(require_scope("charters.read")),
    db: AsyncSession = Depends(get_db),
) -> CharterRead:
    """Fetch a single charter by ID."""
    charter = await get_charter(db, charter_id)
    if charter is None:
        raise HTTPException(status_code=404, detail="Charter not found")
    return charter


@router.patch("/{charter_id}", response_model=CharterRead)
async def update_charter_endpoint(
    charter_id: UUID,
    body: CharterUpdate,
    _: None = Depends(require_scope("charters.write")),
    db: AsyncSession = Depends(get_db),
) -> CharterRead:
    """Update an existing charter."""
    charter = await update_charter(db, charter_id, body)
    if charter is None:
        raise HTTPException(status_code=404, detail="Charter not found")
    return charter
