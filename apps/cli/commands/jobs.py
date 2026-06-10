"""Job queue inspection and control CLI commands (including the kill switch)."""

from __future__ import annotations

from uuid import UUID

import typer

from libs.core.clock import utcnow
from libs.core.events import emit_event_sync
from libs.core.types import JobStatus
from libs.storage.base import get_sync_session_factory
from libs.storage.models.jobs import Job

app = typer.Typer(help="Inspect and control queued jobs.")


def _parse_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError:
        typer.echo(f"Invalid UUID: {raw}", err=True)
        raise typer.Exit(code=1) from None


@app.command("list")
def list_jobs(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by job status"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to show"),
) -> None:
    """List recent jobs, newest first."""
    session_factory = get_sync_session_factory()
    with session_factory() as session:
        query = session.query(Job).order_by(Job.created_at.desc())
        if status is not None:
            query = query.filter(Job.status == status)
        jobs = query.limit(limit).all()

    if not jobs:
        typer.echo("No jobs found.")
        return

    typer.echo(f"{'ID':<38} {'Type':<28} {'Status':<11} {'Att':<5} {'Created'}")
    typer.echo("-" * 110)
    for job in jobs:
        attempts = f"{job.attempt_count}/{job.max_attempts}"
        flags = " [cancel?]" if job.cancel_requested else ""
        typer.echo(
            f"{job.id!s:<38} {job.job_type:<28} {job.status!s:<11} "
            f"{attempts:<5} {job.created_at:%Y-%m-%d %H:%M:%S}{flags}"
        )


@app.command()
def show(job_id: str = typer.Argument(..., help="Job UUID")) -> None:
    """Show full job detail including the captured traceback."""
    jid = _parse_uuid(job_id)
    session_factory = get_sync_session_factory()
    with session_factory() as session:
        job = session.get(Job, jid)

    if job is None:
        typer.echo(f"Job {job_id} not found.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"ID:               {job.id}")
    typer.echo(f"Type:             {job.job_type}")
    typer.echo(f"Status:           {job.status}")
    typer.echo(f"Cycle:            {job.cycle_id}")
    typer.echo(f"Priority:         {job.priority}")
    typer.echo(f"Attempts:         {job.attempt_count}/{job.max_attempts}")
    typer.echo(f"Reclaims:         {job.reclaim_count}")
    typer.echo(f"Cancel requested: {job.cancel_requested}")
    typer.echo(f"Created:          {job.created_at}")
    typer.echo(f"Started:          {job.started_at}")
    typer.echo(f"Heartbeat:        {job.heartbeat_at}")
    typer.echo(f"Not before:       {job.not_before}")
    typer.echo(f"Completed:        {job.completed_at}")
    typer.echo(f"Error:            {job.error}")
    detail = job.error_detail or {}
    if detail:
        typer.echo(f"Error class:      {detail.get('error_class')}")
        typer.echo(f"Exception type:   {detail.get('exc_type')}")
        history = detail.get("attempts") or []
        if history:
            typer.echo("Attempt history:")
            for entry in history:
                typer.echo(
                    f"  #{entry.get('attempt')}: [{entry.get('error_class')}] {entry.get('error')}"
                )
        traceback_text = detail.get("traceback")
        if traceback_text:
            typer.echo("\nTraceback (latest attempt):")
            typer.echo(traceback_text)


@app.command()
def cancel(job_id: str = typer.Argument(..., help="Job UUID")) -> None:
    """Cancel a job — the kill switch for stuck or unwanted work.

    Pending/paused jobs cancel immediately. Running jobs get
    ``cancel_requested`` set; the worker's supervisor interrupts any
    in-flight LLM call within seconds and acknowledges.
    """
    jid = _parse_uuid(job_id)
    session_factory = get_sync_session_factory()
    with session_factory() as session:
        job = session.get(Job, jid)
        if job is None:
            typer.echo(f"Job {job_id} not found.", err=True)
            raise typer.Exit(code=1)
        if job.status not in (
            JobStatus.pending,
            JobStatus.claimed,
            JobStatus.running,
            JobStatus.paused,
        ):
            typer.echo(f"Cannot cancel job in status '{job.status}'.", err=True)
            raise typer.Exit(code=1)

        if job.status in (JobStatus.claimed, JobStatus.running):
            job.cancel_requested = True
            emit_event_sync(
                session,
                event_type="job.cancel_requested",
                cycle_id=job.cycle_id,
                payload={"job_id": str(job.id), "job_type": job.job_type},
            )
            session.commit()
            typer.echo(
                f"Cancel requested for running job {job.id}; "
                "the worker will interrupt it within a few seconds."
            )
            return

        job.status = JobStatus.cancelled
        job.completed_at = utcnow()
        emit_event_sync(
            session,
            event_type="job_cancelled",
            cycle_id=job.cycle_id,
            payload={"job_id": str(job.id)},
        )
        session.commit()
        typer.echo(f"Cancelled job {job.id}.")
