"""Domain event emitter -- appends events to the database."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.types import ActorType
from libs.storage.models.events import DomainEvent


async def emit_event(
    session: AsyncSession,
    *,
    event_type: str,
    charter_id: UUID | None = None,
    cycle_id: UUID | None = None,
    payload: dict | None = None,
    actor_type: ActorType = ActorType.system,
    actor_id: str | None = None,
) -> DomainEvent:
    """Create and persist a domain event.

    The event is added to the session but not committed --
    the caller is responsible for committing the transaction.
    """
    event = DomainEvent(
        id=uuid7(),
        charter_id=charter_id,
        cycle_id=cycle_id,
        event_type=event_type,
        payload=payload,
        actor_type=actor_type,
        actor_id=actor_id,
        created_at=utcnow(),
    )
    session.add(event)
    return event
