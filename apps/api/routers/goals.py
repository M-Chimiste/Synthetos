"""Goal-oriented research API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.core.services.goal_service import (
    GoalServiceError,
    create_goal_sync,
    read_goal_report_file,
    stop_goal_sync,
)
from libs.core.services.result_introspection import build_goal_result_summary
from libs.schemas.common import PaginatedResponse
from libs.schemas.goals import GoalAttemptRead, GoalCreate, GoalRead, GoalReportResponse
from libs.schemas.results import GoalResultSummary
from libs.storage.models.goals import GoalAttempt, ResearchGoal

router = APIRouter(prefix="/goals", tags=["goals"])


@router.post("", response_model=GoalRead, status_code=201)
async def create_goal_endpoint(
    body: GoalCreate,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> GoalRead:
    try:
        goal = await db.run_sync(lambda s: create_goal_sync(s, body))
    except GoalServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return GoalRead.model_validate(goal)


@router.get("", response_model=PaginatedResponse[GoalRead])
async def list_goals_endpoint(
    charter_id: UUID | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[GoalRead]:
    query = select(ResearchGoal)
    count_query = select(ResearchGoal.id)
    if charter_id is not None:
        query = query.where(ResearchGoal.charter_id == charter_id)
        count_query = count_query.where(ResearchGoal.charter_id == charter_id)
    if status is not None:
        query = query.where(ResearchGoal.status == status)
        count_query = count_query.where(ResearchGoal.status == status)
    total = len((await db.execute(count_query)).all())
    rows = (
        (
            await db.execute(
                query.order_by(ResearchGoal.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return PaginatedResponse(
        items=[GoalRead.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{goal_id}", response_model=GoalRead)
async def get_goal_endpoint(
    goal_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> GoalRead:
    goal = await db.get(ResearchGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return GoalRead.model_validate(goal)


@router.get("/{goal_id}/attempts", response_model=list[GoalAttemptRead])
async def list_goal_attempts_endpoint(
    goal_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> list[GoalAttemptRead]:
    result = await db.execute(
        select(GoalAttempt)
        .where(GoalAttempt.goal_id == goal_id)
        .order_by(GoalAttempt.attempt_number)
    )
    return [GoalAttemptRead.model_validate(row) for row in result.scalars().all()]


@router.get("/{goal_id}/report", response_model=GoalReportResponse)
async def get_goal_report_endpoint(
    goal_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> GoalReportResponse:
    goal = await db.get(ResearchGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    markdown, json_payload = read_goal_report_file(goal)
    if markdown is None and json_payload is None:
        raise HTTPException(status_code=404, detail="goal report not yet generated")
    return GoalReportResponse(goal_id=goal.id, markdown=markdown, json=json_payload)


@router.get("/{goal_id}/results", response_model=GoalResultSummary)
async def get_goal_results_endpoint(
    goal_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> GoalResultSummary:
    goal = await db.get(ResearchGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return await db.run_sync(lambda s: build_goal_result_summary(s, goal))


@router.post("/{goal_id}/stop", response_model=GoalRead)
async def stop_goal_endpoint(
    goal_id: UUID,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> GoalRead:
    try:
        goal = await db.run_sync(lambda s: stop_goal_sync(s, goal_id))
    except GoalServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return GoalRead.model_validate(goal)
