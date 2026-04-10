"""Skill management CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer

from libs.core.config import get_settings
from libs.skills.loader import discover_skills
from libs.skills.parser import SkillParseError, parse_skill_file
from libs.skills.validator import SkillValidationError, validate_skill
from libs.storage.base import get_sync_session_factory
from libs.storage.models.skills import SkillDefinition

app = typer.Typer(help="Manage skill packages.")


@app.command()
def discover() -> None:
    """Discover skill packages from configured paths."""
    settings = get_settings()
    search_paths = settings.skill_path_list
    first_party_root = Path("skills")

    typer.echo(f"Searching: {', '.join(str(p) for p in search_paths)}")

    discovered = discover_skills(search_paths, first_party_root=first_party_root)

    if not discovered:
        typer.echo("No skills discovered.")
        return

    typer.echo(f"\nDiscovered {len(discovered)} skill(s):\n")
    typer.echo(f"{'Skill ID':<30} {'Version':<12} {'Trust Tier':<25} {'Path'}")
    typer.echo("-" * 100)
    for s in discovered:
        typer.echo(
            f"{s.manifest.id:<30} {s.manifest.version:<12} {s.trust_tier.value:<25} {s.source_path}"
        )
        for w in s.warnings:
            typer.echo(f"  WARNING: {w}")


@app.command("list")
def list_skills() -> None:
    """List skill definitions stored in the database."""
    session_factory = get_sync_session_factory()
    with session_factory() as session:
        skills = session.query(SkillDefinition).order_by(SkillDefinition.discovered_at).all()

    if not skills:
        typer.echo("No skills in database.")
        return

    typer.echo(f"{'Skill ID':<30} {'Version':<12} {'Trust Tier':<25} {'Enabled'}")
    typer.echo("-" * 80)
    for s in skills:
        typer.echo(f"{s.skill_id:<30} {s.version:<12} {s.trust_tier:<25} {s.enabled}")


@app.command()
def validate(path: str = typer.Argument(..., help="Path to a skill.md file")) -> None:
    """Validate a single skill.md file."""
    skill_path = Path(path)
    if not skill_path.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(code=1)

    try:
        manifest, body = parse_skill_file(skill_path)
    except SkillParseError as e:
        typer.echo(f"Parse error: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Parsed: {manifest.id} v{manifest.version}")

    from libs.skills.loader import _infer_trust_tier

    trust_tier = _infer_trust_tier(skill_path, first_party_root=Path("skills"))

    try:
        warnings = validate_skill(manifest, skill_path, trust_tier)
    except SkillValidationError as e:
        typer.echo(f"Validation error: {e}", err=True)
        raise typer.Exit(code=1) from None

    if warnings:
        for w in warnings:
            typer.echo(f"  WARNING: {w}")
    else:
        typer.echo("Validation passed with no warnings.")

    typer.echo("\nManifest:")
    typer.echo(f"  ID:               {manifest.id}")
    typer.echo(f"  Version:          {manifest.version}")
    typer.echo(f"  Phase:            {manifest.phase}")
    typer.echo(f"  Trust tier:       {trust_tier.value}")
    typer.echo(f"  Risk level:       {manifest.risk_level}")
    typer.echo(f"  Operators:        {manifest.allowed_operators}")
    typer.echo(f"  Capabilities:     {manifest.capabilities}")
    typer.echo(f"  Body length:      {len(body)} chars")
