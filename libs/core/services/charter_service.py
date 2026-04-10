"""Business logic for research charter operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.events import emit_event
from libs.core.types import ActorType, CharterStatus
from libs.schemas.charter import CharterCreate, CharterRead, CharterUpdate
from libs.storage.models.research import ResearchCharter


async def create_charter(
    session: AsyncSession,
    data: CharterCreate,
    *,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> CharterRead:
    """Create a new research charter and emit a creation event."""
    charter = ResearchCharter(
        id=uuid7(),
        title=data.title,
        description=data.description,
        problem_statement=data.problem_statement,
        source_scope=data.source_scope,
        status=CharterStatus.active,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(charter)

    await emit_event(
        session,
        event_type="research_charter_created",
        charter_id=charter.id,
        payload={"title": charter.title},
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return CharterRead.model_validate(charter)


async def get_charter(session: AsyncSession, charter_id: UUID) -> CharterRead | None:
    """Fetch a charter by ID."""
    result = await session.execute(
        select(ResearchCharter).where(ResearchCharter.id == charter_id)
    )
    charter = result.scalar_one_or_none()
    if charter is None:
        return None
    return CharterRead.model_validate(charter)


async def list_charters(
    session: AsyncSession, *, offset: int = 0, limit: int = 50
) -> tuple[list[CharterRead], int]:
    """List charters with pagination."""
    count_result = await session.execute(
        select(ResearchCharter.id)
    )
    total = len(count_result.all())

    result = await session.execute(
        select(ResearchCharter)
        .order_by(ResearchCharter.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    charters = [CharterRead.model_validate(c) for c in result.scalars().all()]
    return charters, total


async def update_charter(
    session: AsyncSession,
    charter_id: UUID,
    data: CharterUpdate,
) -> CharterRead | None:
    """Update an existing charter."""
    result = await session.execute(
        select(ResearchCharter).where(ResearchCharter.id == charter_id)
    )
    charter = result.scalar_one_or_none()
    if charter is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(charter, field_name, value)
    charter.updated_at = utcnow()

    await session.flush()
    return CharterRead.model_validate(charter)
