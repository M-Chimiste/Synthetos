"""Assemble the ResearchState aggregate from related tables."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.types import CycleStatus
from libs.schemas.events import EventRead
from libs.schemas.state import CycleSummary, ResearchStateSnapshot
from libs.storage.models.events import DomainEvent
from libs.storage.models.jobs import Job
from libs.storage.models.research import ResearchCharter, ResearchCycle


async def assemble_research_state(
    session: AsyncSession, charter_id: UUID
) -> ResearchStateSnapshot | None:
    """Build a read-only snapshot of all state for a charter.

    Returns None if the charter does not exist.
    """
    # Fetch charter
    charter_result = await session.execute(
        select(ResearchCharter).where(ResearchCharter.id == charter_id)
    )
    charter = charter_result.scalar_one_or_none()
    if charter is None:
        return None

    # Fetch cycles
    cycles_result = await session.execute(
        select(ResearchCycle)
        .where(ResearchCycle.charter_id == charter_id)
        .order_by(ResearchCycle.created_at.desc())
    )
    cycles = cycles_result.scalars().all()

    cycle_summaries = [
        CycleSummary(
            id=c.id,
            status=CycleStatus(c.status),
            created_at=c.created_at,
            started_at=c.started_at,
            completed_at=c.completed_at,
        )
        for c in cycles
    ]

    # Active cycle: first non-closed cycle
    active_cycle = next(
        (s for s in cycle_summaries if s.status != CycleStatus.closed), None
    )

    # Count events
    event_count_result = await session.execute(
        select(func.count(DomainEvent.id)).where(
            DomainEvent.charter_id == charter_id
        )
    )
    total_events = event_count_result.scalar() or 0

    # Count jobs across all cycles in this charter
    cycle_ids = [c.id for c in cycles]
    if cycle_ids:
        job_count_result = await session.execute(
            select(func.count(Job.id)).where(Job.cycle_id.in_(cycle_ids))
        )
        total_jobs = job_count_result.scalar() or 0
    else:
        total_jobs = 0

    # Recent events (last 20)
    recent_events_result = await session.execute(
        select(DomainEvent)
        .where(DomainEvent.charter_id == charter_id)
        .order_by(DomainEvent.created_at.desc())
        .limit(20)
    )
    recent_events = [
        EventRead.model_validate(e).model_dump(mode="json")
        for e in recent_events_result.scalars().all()
    ]

    return ResearchStateSnapshot(
        charter_id=charter.id,
        charter_title=charter.title,
        charter_status=charter.status,
        cycles=cycle_summaries,
        active_cycle=active_cycle,
        total_events=total_events,
        total_jobs=total_jobs,
        recent_events=recent_events,
    )
