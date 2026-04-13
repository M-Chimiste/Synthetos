"""Phase 4 remediation API router -- remediation actions, signals, frontiers, recommendations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from sqlalchemy import select

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.schemas.remediation import (
    DirectionalSignalRead,
    MetricFrontierRead,
    RemediationActionRead,
    RunLineageRead,
    RunRecommendationRead,
)
from libs.storage.models.experiment import RunRecord
from libs.storage.models.remediation import (
    DirectionalSignal,
    MetricFrontier,
    RemediationAction,
    RunRecommendation,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["remediation"])


# ---------------------------------------------------------------------------
# Remediation actions
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{run_id}/remediation",
    response_model=list[RemediationActionRead],
    dependencies=[Depends(require_scope("read"))],
)
async def get_run_remediation(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[RemediationActionRead]:
    """Get remediation actions for a specific run."""
    result = await db.execute(
        select(RemediationAction)
        .where(RemediationAction.run_record_id == run_id)
        .order_by(RemediationAction.created_at.asc())
    )
    rows = result.scalars().all()
    return [RemediationActionRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Directional signal
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{run_id}/signal",
    response_model=DirectionalSignalRead | None,
    dependencies=[Depends(require_scope("read"))],
)
async def get_run_signal(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> DirectionalSignalRead | None:
    """Get the directional signal for a specific run."""
    result = await db.execute(
        select(DirectionalSignal).where(DirectionalSignal.run_record_id == run_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return DirectionalSignalRead.model_validate(row)


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{run_id}/recommendation",
    response_model=RunRecommendationRead | None,
    dependencies=[Depends(require_scope("read"))],
)
async def get_run_recommendation(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> RunRecommendationRead | None:
    """Get the recommendation for a specific run."""
    result = await db.execute(
        select(RunRecommendation).where(RunRecommendation.run_record_id == run_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return RunRecommendationRead.model_validate(row)


# ---------------------------------------------------------------------------
# Run lineage
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{run_id}/lineage",
    response_model=RunLineageRead,
    dependencies=[Depends(require_scope("read"))],
)
async def get_run_lineage(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> RunLineageRead:
    """Get the full retry lineage for a run (walk parent_run_id chain)."""
    run_ids: list[UUID] = []
    current_id: UUID | None = run_id

    # Walk backwards to find the root
    while current_id is not None:
        run_ids.append(current_id)
        result = await db.execute(
            select(RunRecord.parent_run_id).where(RunRecord.id == current_id)
        )
        parent = result.scalar_one_or_none()
        current_id = parent

    run_ids.reverse()  # Root first

    # Also find children (runs that have this run as parent)
    result = await db.execute(
        select(RunRecord.id)
        .where(RunRecord.parent_run_id == run_id)
        .order_by(RunRecord.created_at.asc())
    )
    children = result.scalars().all()
    for child_id in children:
        if child_id not in run_ids:
            run_ids.append(child_id)

    # Load remediation actions for all runs in lineage
    result = await db.execute(
        select(RemediationAction)
        .where(RemediationAction.run_record_id.in_(run_ids))
        .order_by(RemediationAction.created_at.asc())
    )
    actions = result.scalars().all()

    return RunLineageRead(
        run_ids=run_ids,
        remediation_actions=[RemediationActionRead.model_validate(a) for a in actions],
    )


# ---------------------------------------------------------------------------
# Signal history
# ---------------------------------------------------------------------------


@router.get(
    "/specs/{spec_id}/signal-history",
    response_model=list[DirectionalSignalRead],
    dependencies=[Depends(require_scope("read"))],
)
async def get_spec_signal_history(
    spec_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[DirectionalSignalRead]:
    """Get all directional signals for a spec, ordered chronologically."""
    result = await db.execute(
        select(DirectionalSignal)
        .where(DirectionalSignal.experiment_spec_id == spec_id)
        .order_by(DirectionalSignal.created_at.asc())
    )
    rows = result.scalars().all()
    return [DirectionalSignalRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Metric frontiers
# ---------------------------------------------------------------------------


@router.get(
    "/hypotheses/{card_id}/frontier",
    response_model=MetricFrontierRead | None,
    dependencies=[Depends(require_scope("read"))],
)
async def get_hypothesis_frontier(
    card_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> MetricFrontierRead | None:
    """Get the metric frontier for a hypothesis line."""
    result = await db.execute(
        select(MetricFrontier).where(
            MetricFrontier.hypothesis_card_id == card_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return MetricFrontierRead.model_validate(row)


@router.get(
    "/charters/{charter_id}/frontiers",
    response_model=list[MetricFrontierRead],
    dependencies=[Depends(require_scope("read"))],
)
async def list_charter_frontiers(
    charter_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[MetricFrontierRead]:
    """List all metric frontiers for a charter."""
    result = await db.execute(
        select(MetricFrontier)
        .where(MetricFrontier.charter_id == charter_id)
        .order_by(MetricFrontier.updated_at.desc())
    )
    rows = result.scalars().all()
    return [MetricFrontierRead.model_validate(r) for r in rows]
