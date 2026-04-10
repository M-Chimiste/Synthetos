"""Synthetos CLI -- Typer application entry point."""

from __future__ import annotations

import typer

from libs.core.logging import setup_logging

app = typer.Typer(name="synthetos", help="Synthetos ML Laboratory CLI")


def _setup() -> None:
    """Common setup for all CLI commands."""
    setup_logging(log_level="WARNING")


@app.callback()
def main() -> None:
    """Synthetos ML Laboratory -- research loop management."""
    _setup()


def _register_subcommands() -> None:
    from apps.cli.commands.charter import app as charter_app
    from apps.cli.commands.corpus import app as corpus_app
    from apps.cli.commands.cycle import app as cycle_app
    from apps.cli.commands.db import app as db_app
    from apps.cli.commands.discovery import app as discovery_app
    from apps.cli.commands.skill import app as skill_app

    app.add_typer(charter_app, name="charter")
    app.add_typer(cycle_app, name="cycle")
    app.add_typer(skill_app, name="skill")
    app.add_typer(db_app, name="db")
    app.add_typer(corpus_app, name="corpus")
    app.add_typer(discovery_app, name="discovery")


_register_subcommands()

if __name__ == "__main__":
    app()
