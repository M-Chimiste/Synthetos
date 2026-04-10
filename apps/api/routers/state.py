"""Research state snapshot endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.core.research_state import assemble_research_state
from libs.schemas.state import ResearchStateSnapshot

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/state", tags=["state"])


@router.get("/{charter_id}", response_model=ResearchStateSnapshot)
async def get_research_state(
    charter_id: UUID,
    _: None = Depends(require_scope("state.read")),
    db: AsyncSession = Depends(get_db),
) -> ResearchStateSnapshot:
    """Return the assembled research state for a charter."""
    snapshot = await assemble_research_state(db, charter_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Charter not found")
    return snapshot
