"""Charter management CLI commands."""

from __future__ import annotations

from uuid import UUID

import typer
import uuid_utils

from libs.core.clock import utcnow
from libs.core.types import CharterStatus
from libs.storage.base import get_sync_session_factory
from libs.storage.models.research import ResearchCharter

app = typer.Typer(help="Manage research charters.")


@app.command()
def create(title: str = typer.Argument(..., help="Charter title")) -> None:
    """Create a new research charter."""
    description = typer.prompt("Description", default="")
    problem_statement = typer.prompt("Problem statement", default="")

    charter_id = uuid_utils.uuid7()
    now = utcnow()

    session_factory = get_sync_session_factory()
    with session_factory() as session:
        charter = ResearchCharter(
            id=charter_id,
            title=title,
            description=description,
            problem_statement=problem_statement,
            status=CharterStatus.active,
            created_at=now,
            updated_at=now,
        )
        session.add(charter)
        session.commit()

    typer.echo(f"Created charter {charter_id}  --  {title}")


@app.command("list")
def list_charters() -> None:
    """List all research charters."""
    session_factory = get_sync_session_factory()
    with session_factory() as session:
        charters = session.query(ResearchCharter).order_by(ResearchCharter.created_at).all()

    if not charters:
        typer.echo("No charters found.")
        return

    typer.echo(f"{'ID':<38} {'Status':<12} {'Title'}")
    typer.echo("-" * 80)
    for c in charters:
        typer.echo(f"{c.id!s:<38} {c.status:<12} {c.title}")


@app.command()
def show(charter_id: str = typer.Argument(..., help="Charter UUID")) -> None:
    """Show details of a research charter."""
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

    typer.echo(f"ID:                {charter.id}")
    typer.echo(f"Title:             {charter.title}")
    typer.echo(f"Status:            {charter.status}")
    typer.echo(f"Description:       {charter.description}")
    typer.echo(f"Problem statement: {charter.problem_statement}")
    typer.echo(f"Source scope:      {charter.source_scope}")
    typer.echo(f"Created:           {charter.created_at}")
    typer.echo(f"Updated:           {charter.updated_at}")
