"""Business logic for research cycle operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.events import emit_event
from libs.core.state_machine import validate_transition
from libs.core.types import ActorType, CycleStatus
from libs.schemas.cycle import CycleCreate, CycleRead
from libs.storage.models.research import ResearchCycle


async def create_cycle(
    session: AsyncSession,
    data: CycleCreate,
    *,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> CycleRead:
    """Create a new research cycle for a charter."""
    cycle = ResearchCycle(
        id=uuid7(),
        charter_id=data.charter_id,
        status=CycleStatus.created,
        config=data.config,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(cycle)

    await emit_event(
        session,
        event_type="research_cycle_created",
        charter_id=data.charter_id,
        cycle_id=cycle.id,
        payload={"status": cycle.status.value},
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return CycleRead.model_validate(cycle)


async def get_cycle(session: AsyncSession, cycle_id: UUID) -> CycleRead | None:
    """Fetch a cycle by ID."""
    result = await session.execute(
        select(ResearchCycle).where(ResearchCycle.id == cycle_id)
    )
    cycle = result.scalar_one_or_none()
    if cycle is None:
        return None
    return CycleRead.model_validate(cycle)


async def list_cycles(
    session: AsyncSession,
    *,
    charter_id: UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[CycleRead], int]:
    """List cycles with optional charter filter and pagination."""
    query = select(ResearchCycle)
    if charter_id is not None:
        query = query.where(ResearchCycle.charter_id == charter_id)

    count_result = await session.execute(
        select(ResearchCycle.id).where(
            ResearchCycle.charter_id == charter_id if charter_id else True
        )
    )
    total = len(count_result.all())

    result = await session.execute(
        query.order_by(ResearchCycle.created_at.desc()).offset(offset).limit(limit)
    )
    cycles = [CycleRead.model_validate(c) for c in result.scalars().all()]
    return cycles, total


async def transition_cycle(
    session: AsyncSession,
    cycle_id: UUID,
    target_status: CycleStatus,
    *,
    actor_type: ActorType = ActorType.system,
    actor_id: str | None = None,
) -> CycleRead:
    """Transition a cycle to a new status.

    Raises InvalidTransitionError if the transition is not allowed.
    """
    result = await session.execute(
        select(ResearchCycle).where(ResearchCycle.id == cycle_id)
    )
    cycle = result.scalar_one()

    current = CycleStatus(cycle.status)
    validate_transition(current, target_status)

    cycle.status = target_status
    cycle.updated_at = utcnow()

    if target_status == CycleStatus.discovery_ready and cycle.started_at is None:
        cycle.started_at = utcnow()
    if target_status == CycleStatus.closed:
        cycle.completed_at = utcnow()

    await emit_event(
        session,
        event_type="research_cycle_transitioned",
        charter_id=cycle.charter_id,
        cycle_id=cycle.id,
        payload={
            "from_status": current.value,
            "to_status": target_status.value,
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return CycleRead.model_validate(cycle)
