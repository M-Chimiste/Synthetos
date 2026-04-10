"""Server-Sent Events (SSE) streaming endpoint for domain events."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.schemas.events import EventRead
from libs.storage.models.events import DomainEvent

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/events", tags=["events"])

_POLL_INTERVAL = 0.5  # seconds


async def _event_stream(
    db: AsyncSession,
    charter_id: UUID | None,
    cycle_id: UUID | None,
    last_event_id: UUID | None,
) -> AsyncGenerator[str]:
    """Async generator that polls for new domain events and yields SSE frames."""
    cursor = last_event_id

    while True:
        query = select(DomainEvent).order_by(DomainEvent.created_at.asc())

        if charter_id is not None:
            query = query.where(DomainEvent.charter_id == charter_id)
        if cycle_id is not None:
            query = query.where(DomainEvent.cycle_id == cycle_id)
        if cursor is not None:
            # Fetch events created after the cursor event.
            # UUIDv7 IDs are time-sortable, so id > cursor works.
            query = query.where(DomainEvent.id > cursor)

        query = query.limit(100)

        result = await db.execute(query)
        events = result.scalars().all()

        for event in events:
            data = EventRead.model_validate(event)
            payload = json.dumps(data.model_dump(mode="json"), default=str)
            yield f"id: {data.id}\ndata: {payload}\n\n"
            cursor = event.id

        await asyncio.sleep(_POLL_INTERVAL)


@router.get("/stream")
async def stream_events(
    charter_id: UUID | None = Query(default=None),
    cycle_id: UUID | None = Query(default=None),
    last_event_id: UUID | None = Query(default=None),
    _: None = Depends(require_scope("events.read")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream domain events as Server-Sent Events.

    Polls the domain_events table every 500ms for new events.
    Accepts optional filters for charter_id, cycle_id, and a
    cursor (last_event_id) for resumable streaming.
    """
    return StreamingResponse(
        _event_stream(db, charter_id, cycle_id, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
