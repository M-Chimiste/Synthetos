"""Cycle management CLI commands."""

from __future__ import annotations

from uuid import UUID

import typer
import uuid_utils

from libs.core.clock import utcnow
from libs.core.types import CycleStatus
from libs.storage.base import get_sync_session_factory
from libs.storage.models.research import ResearchCharter, ResearchCycle

app = typer.Typer(help="Manage research cycles.")


@app.command()
def create(charter_id: str = typer.Argument(..., help="Charter UUID")) -> None:
    """Create a new research cycle for a charter."""
    try:
        cid = UUID(charter_id)
    except ValueError:
        typer.echo(f"Invalid UUID: {charter_id}", err=True)
        raise typer.Exit(code=1) from None

    session_factory = get_sync_session_factory()
    with session_factory() as session:
        charter = session.get(ResearchCharter, cid)
        if charter is None:
            typer.echo(f"Charter {charter_id} not found.", err=True)
            raise typer.Exit(code=1)

        cycle_id = uuid_utils.uuid7()
        now = utcnow()

        cycle = ResearchCycle(
            id=cycle_id,
            charter_id=cid,
            status=CycleStatus.created,
            created_at=now,
            updated_at=now,
        )
        session.add(cycle)
        session.commit()

    typer.echo(f"Created cycle {cycle_id} for charter {charter_id}")


@app.command("list")
def list_cycles(
    charter_id: str | None = typer.Option(
        None, "--charter-id", "-c", help="Filter by charter UUID"
    ),
) -> None:
    """List research cycles."""
    session_factory = get_sync_session_factory()
    with session_factory() as session:
        query = session.query(ResearchCycle).order_by(ResearchCycle.created_at)
        if charter_id is not None:
            try:
                cid = UUID(charter_id)
            except ValueError:
                typer.echo(f"Invalid UUID: {charter_id}", err=True)
                raise typer.Exit(code=1) from None
            query = query.filter(ResearchCycle.charter_id == cid)

        cycles = query.all()

    if not cycles:
        typer.echo("No cycles found.")
        return

    typer.echo(f"{'ID':<38} {'Charter ID':<38} {'Status'}")
    typer.echo("-" * 100)
    for c in cycles:
        typer.echo(f"{c.id!s:<38} {c.charter_id!s:<38} {c.status}")


@app.command()
def show(cycle_id: str = typer.Argument(..., help="Cycle UUID")) -> None:
    """Show details of a research cycle."""
    try:
        cid = UUID(cycle_id)
    except ValueError:
        typer.echo(f"Invalid UUID: {cycle_id}", err=True)
        raise typer.Exit(code=1) from None

    session_factory = get_sync_session_factory()
    with session_factory() as session:
        cycle = session.get(ResearchCycle, cid)

    if cycle is None:
        typer.echo(f"Cycle {cycle_id} not found.", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"ID:           {cycle.id}")
    typer.echo(f"Charter ID:   {cycle.charter_id}")
    typer.echo(f"Status:       {cycle.status}")
    typer.echo(f"Config:       {cycle.config}")
    typer.echo(f"Created:      {cycle.created_at}")
    typer.echo(f"Updated:      {cycle.updated_at}")
    typer.echo(f"Started:      {cycle.started_at}")
    typer.echo(f"Completed:    {cycle.completed_at}")
