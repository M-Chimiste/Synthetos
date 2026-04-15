"""Phase 5 autonomy API router -- policy, budget, decisions, gate resume, stop."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.autonomy.policy import AutonomyPolicy
from libs.core.clock import utcnow
from libs.core.events import emit_event
from libs.core.services.autonomy_service import read_report_file
from libs.core.types import CycleStatus, JobStatus
from libs.schemas.autonomy import (
    AutonomyBudgetRead,
    AutonomyPolicyRead,
    AutonomyPolicyUpdate,
    AutonomyReportResponse,
    LoopDecisionRead,
)
from libs.storage.models.autonomy import AutonomyBudget, LoopDecision
from libs.storage.models.jobs import Job
from libs.storage.models.remediation import RunRecommendation
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


@router.get(
    "/cycles/{cycle_id}/autonomy/report",
    response_model=AutonomyReportResponse,
    dependencies=[Depends(require_scope("cycles.read"))],
)
async def get_autonomy_report(
    cycle_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> AutonomyReportResponse:
    report = await read_report_file(db, cycle_id)
    if report.markdown is None and report.json_payload is None:
        raise HTTPException(status_code=404, detail="autonomy report not yet generated")
    return report


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

    budget_result = await db.execute(
        select(AutonomyBudget).where(AutonomyBudget.cycle_id == cycle_id)
    )
    budget = budget_result.scalar_one_or_none()

    recommendation_id = None
    fallback_run_record_id = None
    decision_result = await db.execute(
        select(LoopDecision)
        .where(LoopDecision.cycle_id == cycle_id)
        .order_by(LoopDecision.created_at.desc())
        .limit(1)
    )
    last_decision = decision_result.scalar_one_or_none()
    if last_decision is not None:
        recommendation_id = last_decision.recommendation_id
    else:
        rec_result = await db.execute(
            select(RunRecommendation)
            .where(RunRecommendation.cycle_id == cycle_id)
            .order_by(RunRecommendation.created_at.desc())
            .limit(1)
        )
        latest_recommendation = rec_result.scalar_one_or_none()
        recommendation_id = latest_recommendation.id if latest_recommendation else None
        fallback_run_record_id = (
            latest_recommendation.run_record_id if latest_recommendation is not None else None
        )
    if last_decision is not None:
        fallback_run_record_id = last_decision.run_record_id

    if recommendation_id is not None and fallback_run_record_id is not None:
        manual_decision = LoopDecision(
            id=uuid7(),
            cycle_id=cycle_id,
            charter_id=cycle.charter_id,
            run_record_id=fallback_run_record_id,
            recommendation_id=recommendation_id,
            iteration_number=(
                (last_decision.iteration_number + 1)
                if last_decision is not None
                else 1
            ),
            decision="stop_manual",
            gate_triggered=None,
            budget_snapshot={
                "total_runs": budget.total_runs if budget else 0,
                "wall_clock_elapsed_s": budget.wall_clock_elapsed_s if budget else 0.0,
                "runs_per_hypothesis": budget.runs_per_hypothesis if budget else {},
            },
            hypothesis_card_id=(
                last_decision.hypothesis_card_id
                if last_decision is not None
                else None
            ),
            next_hypothesis_card_id=None,
            next_action=None,
            context_summary_path=(
                last_decision.context_summary_path
                if last_decision is not None
                else None
            ),
            reasoning="Manual stop requested.",
            created_at=utcnow(),
        )
        db.add(manual_decision)

    # Transition to reporting if in loop_deciding
    if cycle.status in (CycleStatus.loop_deciding, CycleStatus.running):
        cycle.status = CycleStatus.reporting
        cycle.updated_at = utcnow()

        # Enqueue loop_report
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
