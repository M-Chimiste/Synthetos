"""Job list and control endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from apps.api.deps import get_db
from libs.core.clock import utcnow
from libs.core.types import JobStatus
from libs.schemas.common import PaginatedResponse
from libs.schemas.jobs import JobRead
from libs.storage.models.jobs import Job

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=PaginatedResponse[JobRead])
async def list_jobs(
    cycle_id: UUID | None = Query(default=None),
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[JobRead]:
    """List jobs with optional cycle filter and pagination."""
    query = select(Job)
    count_query = select(Job.id)

    if cycle_id is not None:
        query = query.where(Job.cycle_id == cycle_id)
        count_query = count_query.where(Job.cycle_id == cycle_id)

    count_result = await db.execute(count_query)
    total = len(count_result.all())

    result = await db.execute(
        query.order_by(Job.created_at.desc()).offset(offset).limit(limit)
    )
    items = [JobRead.model_validate(j) for j in result.scalars().all()]
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    """Fetch a single job by ID."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobRead.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobRead)
async def cancel_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    """Cancel a pending or running job."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.pending, JobStatus.claimed, JobStatus.running):
        raise HTTPException(status_code=409, detail=f"Cannot cancel job in status '{job.status}'")
    job.status = JobStatus.cancelled
    job.completed_at = utcnow()
    await db.commit()
    return JobRead.model_validate(job)
