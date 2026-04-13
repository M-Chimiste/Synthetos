"""CLI commands for Phase 3 hypotheses, protocols, and experiment execution."""

from __future__ import annotations

import asyncio
from uuid import UUID

import typer

from libs.core.logging import get_logger

app = typer.Typer(help="Experiment pipeline commands (hypotheses, protocols, runs)")
log = get_logger("cli.experiment")


# ---- Hypotheses ------------------------------------------------------------


@app.command("hypothesize")
def hypothesize(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
    charter_id: str = typer.Option(..., "--charter-id", help="UUID of the charter"),
) -> None:
    """Start hypothesis generation for a cycle."""
    asyncio.run(_start_hypothesize(UUID(cycle_id), UUID(charter_id)))


async def _start_hypothesize(cycle_id: UUID, charter_id: UUID) -> None:
    from libs.core.services.experiment_service import (
        ExperimentServiceError,
        start_hypothesis_session,
    )
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        try:
            session_read, job_id = await start_hypothesis_session(
                db, cycle_id=cycle_id, charter_id=charter_id
            )
            await db.commit()
            typer.echo(f"Hypothesis session {session_read.id} created. Job: {job_id}")
        except ExperimentServiceError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc


@app.command("hypotheses")
def list_hypotheses(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
    status: str | None = typer.Option(None, "--status", help="Filter by status"),
) -> None:
    """List hypothesis cards for a cycle."""
    asyncio.run(_list_hypotheses(UUID(cycle_id), status))


async def _list_hypotheses(cycle_id: UUID, status: str | None) -> None:
    from libs.core.services.experiment_service import list_hypothesis_cards
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        items, total = await list_hypothesis_cards(
            db, cycle_id=cycle_id, status=status, limit=20
        )
        typer.echo(f"Total: {total}")
        for c in items:
            rank_str = f"#{c.rank}" if c.rank else "unranked"
            typer.echo(
                f"  {c.id}  {rank_str:>10}  [{c.status}]  {c.title[:60]}"
            )


# ---- Experiment specs ------------------------------------------------------


@app.command("specs")
def list_specs(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
) -> None:
    """List experiment specs for a cycle."""
    asyncio.run(_list_specs(UUID(cycle_id)))


async def _list_specs(cycle_id: UUID) -> None:
    from libs.core.services.experiment_service import list_experiment_specs
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        items, total = await list_experiment_specs(db, cycle_id=cycle_id, limit=20)
        typer.echo(f"Total: {total}")
        for s in items:
            typer.echo(f"  {s.id}  [{s.status}]  {s.title[:60]}")


# ---- Runs ------------------------------------------------------------------


@app.command("runs")
def list_runs(
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
) -> None:
    """List experiment runs for a cycle."""
    asyncio.run(_list_runs(UUID(cycle_id)))


async def _list_runs(cycle_id: UUID) -> None:
    from libs.core.services.experiment_service import list_run_records
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        items, total = await list_run_records(db, cycle_id=cycle_id, limit=20)
        typer.echo(f"Total: {total}")
        for r in items:
            exit_str = f"exit={r.exit_code}" if r.exit_code is not None else ""
            typer.echo(
                f"  {r.id}  run#{r.run_number}  [{r.status}]  {exit_str}"
            )


@app.command("status")
def run_status(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Show detailed status of an experiment run."""
    asyncio.run(_run_status(UUID(run_id)))


async def _run_status(run_id: UUID) -> None:
    from libs.core.services.experiment_service import get_run_record
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        r = await get_run_record(db, run_id)
        if r is None:
            typer.echo("Run record not found.")
            raise typer.Exit(code=1)
        typer.echo(f"Run:            {r.id}")
        typer.echo(f"Status:         {r.status}")
        typer.echo(f"Run number:     {r.run_number}")
        typer.echo(f"Image:          {r.image_ref}")
        typer.echo(f"Exit code:      {r.exit_code}")
        typer.echo(f"Failure class:  {r.failure_class}")
        if r.error:
            typer.echo(f"Error:          {r.error}")
        if r.metrics_output:
            typer.echo(f"Metrics:        {r.metrics_output}")
        if r.resource_usage:
            typer.echo(f"Resource usage: {r.resource_usage}")


# ---- Run controls ----------------------------------------------------------


@app.command("pause")
def pause_run(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Pause a running experiment."""
    asyncio.run(_control_run(UUID(run_id), "pause"))


@app.command("resume")
def resume_run(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Resume a paused experiment."""
    asyncio.run(_control_run(UUID(run_id), "resume"))


@app.command("cancel")
def cancel_run(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Cancel a running or paused experiment."""
    asyncio.run(_control_run(UUID(run_id), "cancel"))


@app.command("retry")
def retry_run(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the failed/cancelled run"),
) -> None:
    """Retry a failed or cancelled experiment (creates a new run)."""
    asyncio.run(_control_run(UUID(run_id), "retry"))


async def _control_run(run_id: UUID, action: str) -> None:
    from libs.core.services.experiment_service import (
        ExperimentServiceError,
        control_run,
    )
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        try:
            result = await control_run(db, run_id, action)
            await db.commit()
            typer.echo(f"Action '{action}' applied. Run {result.id} status: {result.status}")
        except ExperimentServiceError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc


# ---- Verification ----------------------------------------------------------


@app.command("verify")
def show_verification(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Show verification report for a run."""
    asyncio.run(_show_verification(UUID(run_id)))


async def _show_verification(run_id: UUID) -> None:
    from libs.core.services.experiment_service import get_verification_report
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        v = await get_verification_report(db, run_id)
        if v is None:
            typer.echo("No verification report found.")
            return
        typer.echo(f"Verdict:  {v.verdict}")
        typer.echo(f"Summary:  {v.summary}")
        if v.warnings:
            for w in v.warnings:
                typer.echo(f"  Warning: {w}")


@app.command("postmortem")
def show_postmortem(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Show failure postmortem for a run."""
    asyncio.run(_show_postmortem(UUID(run_id)))


async def _show_postmortem(run_id: UUID) -> None:
    from libs.core.services.experiment_service import get_failure_postmortem
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        pm = await get_failure_postmortem(db, run_id)
        if pm is None:
            typer.echo("No postmortem found.")
            return
        typer.echo(f"Failure class:  {pm.failure_class}")
        typer.echo(f"Root cause:     {pm.root_cause}")
        if pm.next_step_recommendation:
            typer.echo(f"Next step:      {pm.next_step_recommendation}")


# ---- Remediation (Phase 4) ---------------------------------------------------


@app.command("remediation")
def show_remediation(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Show remediation actions for a run."""
    asyncio.run(_show_remediation(UUID(run_id)))


async def _show_remediation(run_id: UUID) -> None:
    from sqlalchemy import select

    from libs.storage.base import get_async_session
    from libs.storage.models.remediation import RemediationAction

    async with get_async_session() as db:
        result = await db.execute(
            select(RemediationAction)
            .where(RemediationAction.run_record_id == run_id)
            .order_by(RemediationAction.created_at.asc())
        )
        actions = result.scalars().all()
        if not actions:
            typer.echo("No remediation actions for this run.")
            return
        for a in actions:
            typer.echo(
                f"  #{a.attempt_number} {a.strategy} ({a.strategy_tier}) "
                f"→ {a.outcome}"
            )
            if a.reasoning:
                typer.echo(f"    Reason: {a.reasoning}")
            if a.retry_run_id:
                typer.echo(f"    Retry run: {a.retry_run_id}")


@app.command("signal")
def show_signal(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Show directional signal for a run."""
    asyncio.run(_show_signal(UUID(run_id)))


async def _show_signal(run_id: UUID) -> None:
    from sqlalchemy import select

    from libs.storage.base import get_async_session
    from libs.storage.models.remediation import DirectionalSignal

    async with get_async_session() as db:
        result = await db.execute(
            select(DirectionalSignal).where(
                DirectionalSignal.run_record_id == run_id
            )
        )
        sig = result.scalar_one_or_none()
        if sig is None:
            typer.echo("No directional signal for this run.")
            return
        typer.echo(f"Signal:    {sig.signal}")
        typer.echo(f"Metric:    {sig.primary_metric_name} = {sig.primary_metric_value:.4f}")
        if sig.primary_metric_delta is not None:
            typer.echo(f"Delta:     {sig.primary_metric_delta:+.4f}")
        typer.echo(f"Direction: {sig.primary_metric_direction}")
        typer.echo(f"Reasoning: {sig.reasoning}")


@app.command("frontier")
def show_frontier(
    charter_id: str = typer.Option(
        ..., "--charter-id", help="UUID of the charter"
    ),
) -> None:
    """List metric frontiers for a charter."""
    asyncio.run(_show_frontier(UUID(charter_id)))


async def _show_frontier(charter_id: UUID) -> None:
    from sqlalchemy import select

    from libs.storage.base import get_async_session
    from libs.storage.models.remediation import MetricFrontier

    async with get_async_session() as db:
        result = await db.execute(
            select(MetricFrontier)
            .where(MetricFrontier.charter_id == charter_id)
            .order_by(MetricFrontier.updated_at.desc())
        )
        frontiers = result.scalars().all()
        if not frontiers:
            typer.echo("No metric frontiers for this charter.")
            return
        for f in frontiers:
            typer.echo(
                f"  Hypothesis {f.hypothesis_card_id}: "
                f"{f.primary_metric_name}={f.best_metric_value:.4f} "
                f"({f.primary_metric_direction}) "
                f"| {f.runs_since_improvement} runs since improvement "
                f"| {f.successful_runs}/{f.total_runs} successful"
            )


@app.command("recommendation")
def show_recommendation(
    run_id: str = typer.Option(..., "--run-id", help="UUID of the run record"),
) -> None:
    """Show recommendation for a run."""
    asyncio.run(_show_recommendation(UUID(run_id)))


async def _show_recommendation(run_id: UUID) -> None:
    from sqlalchemy import select

    from libs.storage.base import get_async_session
    from libs.storage.models.remediation import RunRecommendation

    async with get_async_session() as db:
        result = await db.execute(
            select(RunRecommendation).where(
                RunRecommendation.run_record_id == run_id
            )
        )
        rec = result.scalar_one_or_none()
        if rec is None:
            typer.echo("No recommendation for this run.")
            return
        typer.echo(f"Type:      {rec.recommendation_type}")
        typer.echo(f"Action:    {rec.action}")
        typer.echo(f"Reasoning: {rec.reasoning}")
