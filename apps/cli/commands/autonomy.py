"""CLI commands for Phase 5 autonomous loop control."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import typer

from libs.core.logging import get_logger

app = typer.Typer(help="Autonomous loop commands (policy, budget, decisions, resume, stop)")
log = get_logger("cli.autonomy")


@app.command("policy")
def show_policy(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
) -> None:
    """Show the current autonomy policy for a cycle."""
    asyncio.run(_show_policy(UUID(cycle_id)))


async def _show_policy(cycle_id: UUID) -> None:
    from libs.autonomy.policy import AutonomyPolicy
    from libs.storage.base import get_async_session
    from libs.storage.models.research import ResearchCycle

    async with get_async_session() as db:
        cycle = await db.get(ResearchCycle, cycle_id)
        if cycle is None:
            typer.echo(f"Cycle {cycle_id} not found", err=True)
            raise typer.Exit(1)
        policy = AutonomyPolicy.model_validate(
            (cycle.config or {}).get("autonomy", {})
        )
        typer.echo(json.dumps(policy.model_dump(), indent=2))


@app.command("budget")
def show_budget(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
) -> None:
    """Show budget consumption for a cycle."""
    asyncio.run(_show_budget(UUID(cycle_id)))


async def _show_budget(cycle_id: UUID) -> None:
    from sqlalchemy import select

    from libs.storage.base import get_async_session
    from libs.storage.models.autonomy import AutonomyBudget

    async with get_async_session() as db:
        result = await db.execute(
            select(AutonomyBudget).where(AutonomyBudget.cycle_id == cycle_id)
        )
        budget = result.scalar_one_or_none()
        if budget is None:
            typer.echo("No budget tracking found for this cycle.")
            return
        typer.echo(f"Total runs:      {budget.total_runs}")
        hours = budget.wall_clock_elapsed_s / 3600.0
        typer.echo(f"Wall-clock time: {hours:.2f} hours")
        typer.echo(f"Runs per hypothesis: {json.dumps(budget.runs_per_hypothesis, indent=2)}")


@app.command("decisions")
def list_decisions(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
) -> None:
    """List all loop decisions for a cycle."""
    asyncio.run(_list_decisions(UUID(cycle_id)))


async def _list_decisions(cycle_id: UUID) -> None:
    from sqlalchemy import select

    from libs.storage.base import get_async_session
    from libs.storage.models.autonomy import LoopDecision

    async with get_async_session() as db:
        result = await db.execute(
            select(LoopDecision)
            .where(LoopDecision.cycle_id == cycle_id)
            .order_by(LoopDecision.iteration_number)
        )
        rows = result.scalars().all()
        if not rows:
            typer.echo("No loop decisions found.")
            return
        for d in rows:
            typer.echo(
                f"#{d.iteration_number}  {d.decision:25s}  "
                f"{d.reasoning[:60] if d.reasoning else ''}"
            )


@app.command("resume")
def resume_gate(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
) -> None:
    """Resume a gate-paused autonomous loop."""
    asyncio.run(_resume(UUID(cycle_id)))


async def _resume(cycle_id: UUID) -> None:
    from sqlalchemy import select, update

    from libs.core.types import JobStatus
    from libs.storage.base import get_async_session
    from libs.storage.models.jobs import Job

    async with get_async_session() as db:
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
            typer.echo("No paused loop_decide job found.", err=True)
            raise typer.Exit(1)

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
        await db.commit()
        typer.echo(f"Resumed job {job.id}")


@app.command("stop")
def stop_loop(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
) -> None:
    """Manually stop an autonomous loop."""
    asyncio.run(_stop(UUID(cycle_id)))


async def _stop(cycle_id: UUID) -> None:
    from sqlalchemy import update

    from libs.core.clock import utcnow
    from libs.core.types import CycleStatus, JobStatus
    from libs.storage.base import get_async_session
    from libs.storage.models.jobs import Job
    from libs.storage.models.research import ResearchCycle

    async with get_async_session() as db:
        cycle = await db.get(ResearchCycle, cycle_id)
        if cycle is None:
            typer.echo(f"Cycle {cycle_id} not found", err=True)
            raise typer.Exit(1)

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

        if cycle.status == CycleStatus.loop_deciding:
            cycle.status = CycleStatus.reporting
            cycle.updated_at = utcnow()

        await db.commit()
        typer.echo(f"Loop stopped. Cycle status: {cycle.status}")
