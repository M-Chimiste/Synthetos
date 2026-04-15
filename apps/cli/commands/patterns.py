"""CLI commands for Phase 6 canonical pattern memory."""

from __future__ import annotations

from uuid import UUID

import typer

from libs.core.services.job_service import create_job
from libs.storage.base import get_sync_session_factory

app = typer.Typer(help="Canonical pattern memory commands.")


@app.command("consolidate")
def consolidate_cmd(
    charter_id: str | None = typer.Option(
        None,
        "--charter-id",
        help="Optional charter scope for consolidation.",
    ),
    pattern_type: list[str] = typer.Option(
        [],
        "--pattern-type",
        help="Optional repeated pattern type filter.",
    ),
) -> None:
    """Enqueue a pattern consolidation job."""
    payload: dict[str, object] = {}
    if charter_id is not None:
        try:
            payload["charter_id"] = str(UUID(charter_id))
        except ValueError as exc:
            typer.secho(f"invalid charter id: {charter_id}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
    if pattern_type:
        payload["pattern_types"] = pattern_type

    factory = get_sync_session_factory()
    with factory() as db:
        job = create_job(
            db,
            cycle_id=None,
            job_type="consolidate_patterns",
            payload=payload or None,
        )
        db.commit()
    typer.echo(f"enqueued consolidate_patterns job {job.id}")


@app.command("decay")
def decay_cmd(
    force: bool = typer.Option(False, "--force", help="Force a decay pass."),
    max_staleness_days: int | None = typer.Option(
        None,
        "--max-staleness-days",
        help="Override the default staleness window for this decay run.",
    ),
) -> None:
    """Enqueue a pattern decay job."""
    payload: dict[str, object] = {"force": force}
    if max_staleness_days is not None:
        payload["max_staleness_days"] = max_staleness_days

    factory = get_sync_session_factory()
    with factory() as db:
        job = create_job(
            db,
            cycle_id=None,
            job_type="decay_patterns",
            payload=payload,
        )
        db.commit()
    typer.echo(f"enqueued decay_patterns job {job.id}")
