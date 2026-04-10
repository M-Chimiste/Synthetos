"""Database management CLI commands."""

from __future__ import annotations

import subprocess
import sys

import typer

app = typer.Typer(help="Database management.")


@app.command("init")
def init() -> None:
    """Run database migrations (alembic upgrade head)."""
    typer.echo("Running alembic upgrade head ...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=False,
    )
    if result.returncode != 0:
        typer.echo("Migration failed.", err=True)
        raise typer.Exit(code=result.returncode)
    typer.echo("Database initialized.")


@app.command()
def migrate(message: str = typer.Argument(..., help="Migration message")) -> None:
    """Generate a new migration (alembic revision --autogenerate)."""
    typer.echo(f"Generating migration: {message}")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", message],
        capture_output=False,
    )
    if result.returncode != 0:
        typer.echo("Migration generation failed.", err=True)
        raise typer.Exit(code=result.returncode)
    typer.echo("Migration created.")
