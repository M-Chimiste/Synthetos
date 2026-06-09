"""CRUD and state-transition endpoints for research cycles."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.core.services.cycle_service import (
    create_cycle,
    get_cycle,
    list_cycles,
    transition_cycle,
)
from libs.core.services.result_introspection import (
    ResultIntrospectionError,
    build_cycle_result_introspection,
)
from libs.schemas.common import PaginatedResponse
from libs.schemas.cycle import CycleCreate, CycleRead, CycleTransition
from libs.schemas.results import CycleResultIntrospection

router = APIRouter(prefix="/cycles", tags=["cycles"])

@router.post("", response_model=CycleRead, status_code=201)
async def create_cycle_endpoint(
    body: CycleCreate,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> CycleRead:
    """Create a new research cycle."""
    return await create_cycle(db, body)

@router.get("", response_model=PaginatedResponse[CycleRead])
async def list_cycles_endpoint(
    charter_id: UUID | None = None,
    offset: int = 0,
    limit: int = 50,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CycleRead]:
    """List research cycles with optional charter filter and pagination."""
    items, total = await list_cycles(db, charter_id=charter_id, offset=offset, limit=limit)
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

@router.get("/{cycle_id}", response_model=CycleRead)
async def get_cycle_endpoint(
    cycle_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> CycleRead:
    """Fetch a single cycle by ID."""
    cycle = await get_cycle(db, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return cycle

@router.get("/{cycle_id}/introspection", response_model=CycleResultIntrospection)
async def get_cycle_introspection_endpoint(
    cycle_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> CycleResultIntrospection:
    """Fetch or build the result introspection bundle for a cycle."""
    try:
        return await db.run_sync(
            lambda s: build_cycle_result_introspection(s, cycle_id, write_files=False)
        )
    except ResultIntrospectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/{cycle_id}/transition", response_model=CycleRead)
async def transition_cycle_endpoint(
    cycle_id: UUID,
    body: CycleTransition,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> CycleRead:
    """Transition a cycle to a new status.

    Returns 409 if the transition is not allowed by the state machine.
    """
    return await transition_cycle(db, cycle_id, body.target_status)
