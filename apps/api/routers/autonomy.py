"""Phase 5 autonomy API router -- policy, budget, decisions, gate resume, stop."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.autonomy.policy import AutonomyPolicy
from libs.core.clock import utcnow
from libs.core.events import emit_event
from libs.core.types import CycleStatus, JobStatus
from libs.schemas.autonomy import (
    AutonomyBudgetRead,
    AutonomyPolicyRead,
    AutonomyPolicyUpdate,
    LoopDecisionRead,
)
from libs.storage.models.autonomy import AutonomyBudget, LoopDecision
from libs.storage.models.jobs import Job
from libs.storage.models.research import ResearchCycle

router = APIRouter(tags=["autonomy"])


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@router.get(
    "/cycles/{cycle_id}/autonomy/policy",
    response_model=AutonomyPolicyRead,
    dependencies=[Depends(require_scope("cycles.read"))],
)
async def get_autonomy_policy(
    cycle_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> AutonomyPolicyRead:
    """Read the current autonomy policy for a cycle."""
    cycle = await db.get(ResearchCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    policy = AutonomyPolicy.model_validate(
        (cycle.config or {}).get("autonomy", {})
    )
    return AutonomyPolicyRead.model_validate(policy.model_dump())


@router.put(
    "/cycles/{cycle_id}/autonomy/policy",
    response_model=AutonomyPolicyRead,
    dependencies=[Depends(require_scope("cycles.write"))],
)
async def update_autonomy_policy(
    cycle_id: UUID,
    body: AutonomyPolicyUpdate,
    db: AsyncSession = Depends(get_db),
) -> AutonomyPolicyRead:
    """Update the autonomy policy for a cycle (e.g., extend budget, toggle gates)."""
    cycle = await db.get(ResearchCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Cycle not found")

    config = dict(cycle.config or {})
    current = config.get("autonomy", {})
    updates = body.model_dump(exclude_none=True)
    current.update(updates)
    config["autonomy"] = current
    cycle.config = config
    cycle.updated_at = utcnow()
    await db.flush()

    policy = AutonomyPolicy.model_validate(current)
    return AutonomyPolicyRead.model_validate(policy.model_dump())


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@router.get(
    "/cycles/{cycle_id}/autonomy/budget",
    response_model=AutonomyBudgetRead | None,
    dependencies=[Depends(require_scope("cycles.read"))],
)
async def get_autonomy_budget(
    cycle_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> AutonomyBudgetRead | None:
    """Read the current budget consumption for a cycle."""
    result = await db.execute(
        select(AutonomyBudget).where(AutonomyBudget.cycle_id == cycle_id)
    )
    budget = result.scalar_one_or_none()
    if budget is None:
        return None
    return AutonomyBudgetRead.model_validate(budget)


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@router.get(
    "/cycles/{cycle_id}/autonomy/decisions",
    response_model=list[LoopDecisionRead],
    dependencies=[Depends(require_scope("cycles.read"))],
)
async def list_loop_decisions(
    cycle_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[LoopDecisionRead]:
    """List all loop decisions for a cycle, ordered by iteration."""
    result = await db.execute(
        select(LoopDecision)
        .where(LoopDecision.cycle_id == cycle_id)
        .order_by(LoopDecision.iteration_number)
    )
    rows = result.scalars().all()
    return [LoopDecisionRead.model_validate(r) for r in rows]


@router.get(
    "/cycles/{cycle_id}/autonomy/decisions/{decision_id}",
    response_model=LoopDecisionRead,
    dependencies=[Depends(require_scope("cycles.read"))],
)
async def get_loop_decision(
    cycle_id: UUID,
    decision_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> LoopDecisionRead:
    """Get a single loop decision."""
    result = await db.execute(
        select(LoopDecision).where(
            LoopDecision.id == decision_id,
            LoopDecision.cycle_id == cycle_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return LoopDecisionRead.model_validate(row)


# ---------------------------------------------------------------------------
# Resume (gate approval)
# ---------------------------------------------------------------------------


@router.post(
    "/cycles/{cycle_id}/autonomy/resume",
    dependencies=[Depends(require_scope("cycles.write"))],
)
async def resume_gate(
    cycle_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resume a gate-paused autonomous loop."""
    result = await db.execute(
        select(Job)
        .where(Job.cycle_id == cycle_id)
        .where(Job.job_type == "loop_decide")
        .where(Job.status == JobStatus.paused)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="No paused loop_decide job found for this cycle",
        )

    # Resume: set back to pending
    await db.execute(
        update(Job)
        .where(Job.id == job.id)
        .values(
            status=JobStatus.pending,
            claimed_by=None,
            claimed_at=None,
            heartbeat_at=None,
        )
    )

    cycle = await db.get(ResearchCycle, cycle_id)
    charter_id = cycle.charter_id if cycle else None
    await emit_event(
        db,
        event_type="autonomy.gate_resumed",
        charter_id=charter_id,
        cycle_id=cycle_id,
        payload={"job_id": str(job.id)},
    )

    return {"resumed_job_id": str(job.id)}


# ---------------------------------------------------------------------------
# Stop (manual halt)
# ---------------------------------------------------------------------------


@router.post(
    "/cycles/{cycle_id}/autonomy/stop",
    dependencies=[Depends(require_scope("cycles.write"))],
)
async def stop_loop(
    cycle_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually stop an autonomous loop."""
    cycle = await db.get(ResearchCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Cycle not found")

    # Cancel all pending/claimed/running jobs for this cycle
    cancellable = [
        JobStatus.pending.value,
        JobStatus.claimed.value,
        JobStatus.running.value,
        JobStatus.paused.value,
    ]
    await db.execute(
        update(Job)
        .where(Job.cycle_id == cycle_id)
        .where(Job.status.in_(cancellable))
        .values(status=JobStatus.cancelled)
    )

    # Transition to reporting if in loop_deciding
    if cycle.status == CycleStatus.loop_deciding:
        cycle.status = CycleStatus.reporting
        cycle.updated_at = utcnow()

        # Enqueue loop_report
        from uuid_utils import uuid7

        report_job = Job(
            id=uuid7(),
            cycle_id=cycle_id,
            job_type="loop_report",
            status=JobStatus.pending,
            payload={"cycle_id": str(cycle_id)},
            priority=5,
            created_at=utcnow(),
        )
        db.add(report_job)

    await emit_event(
        db,
        event_type="autonomy.loop_stopped_manual",
        charter_id=cycle.charter_id,
        cycle_id=cycle_id,
        payload={"reason": "manual_stop"},
    )

    return {"status": "stopped", "cycle_status": cycle.status}
