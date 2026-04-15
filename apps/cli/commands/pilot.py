"""Pilot harness CLI commands (Phase 6 §4)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import typer

from libs.pilot.evaluation import (
    compare_evaluations,
    evaluate_cycle,
    load_evaluation,
    write_comparison,
    write_evaluation,
)
from libs.pilot.fixture import (
    VALID_TIERS,
    PilotFixtureError,
    list_fixtures,
    load_fixture,
)
from libs.pilot.runner import start_pilot

app = typer.Typer(help="Run and inspect pilot fixtures.")

DEFAULT_FIXTURE_ROOT = Path("configs/problems")


@app.command("list")
def list_cmd(
    root: Path = typer.Option(
        DEFAULT_FIXTURE_ROOT,
        "--root",
        help="Fixture directory (defaults to configs/problems/).",
    ),
) -> None:
    """List every pilot fixture available under the fixture root."""
    ids = list_fixtures(root)
    if not ids:
        typer.echo(f"No fixtures found under {root}.")
        raise typer.Exit(code=0)
    for pid in ids:
        typer.echo(pid)


@app.command("validate")
def validate_cmd(
    problem_id: str = typer.Argument(..., help="Fixture directory name."),
    root: Path = typer.Option(DEFAULT_FIXTURE_ROOT, "--root"),
) -> None:
    """Validate a fixture's contract without running it."""
    try:
        fixture = load_fixture(root / problem_id)
    except PilotFixtureError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Fixture '{fixture.problem_id}' is valid.")
    typer.echo(f"  tier: {fixture.tier}")
    typer.echo(f"  mode: {fixture.autonomy.get('mode')}")
    typer.echo(f"  budget runs: {fixture.autonomy.get('max_total_runs')}")


@app.command("show")
def show_cmd(
    problem_id: str = typer.Argument(...),
    root: Path = typer.Option(DEFAULT_FIXTURE_ROOT, "--root"),
) -> None:
    """Print a fixture's charter + autonomy summary."""
    try:
        fixture = load_fixture(root / problem_id)
    except PilotFixtureError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"# {fixture.charter.get('title')}")
    typer.echo(f"Tier: {fixture.tier}")
    typer.echo(f"Domain: {fixture.charter.get('domain')}")
    typer.echo("")
    typer.echo(fixture.charter.get("problem_statement", ""))
    typer.echo("")
    typer.echo("Success criteria:")
    for c in fixture.charter.get("success_criteria", []) or []:
        typer.echo(f"  - {c}")


@app.command("run")
def run_cmd(
    problem_id: str = typer.Argument(..., help="Fixture directory name."),
    root: Path = typer.Option(DEFAULT_FIXTURE_ROOT, "--root"),
    tier: str | None = typer.Option(
        None,
        "--tier",
        help="Require the fixture to match this tier before running.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate the fixture and print the planned kickoff without mutating the DB.",
    ),
) -> None:
    """Start a new pilot cycle from a fixture.

    Creates (or reuses) the pilot charter, inserts a fresh cycle configured
    from the fixture, and prints the charter/cycle IDs. A running worker
    picks up the chain from there.
    """
    try:
        fixture = load_fixture(root / problem_id)
    except PilotFixtureError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    if tier is not None and tier not in VALID_TIERS:
        typer.secho(
            f"tier must be one of {sorted(VALID_TIERS)}, got '{tier}'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if tier is not None and fixture.tier != tier:
        typer.secho(
            f"fixture tier mismatch: expected {tier}, fixture is {fixture.tier}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if dry_run:
        typer.echo(f"Fixture '{fixture.problem_id}' is valid and ready.")
        typer.echo(f"  tier: {fixture.tier}")
        typer.echo(f"  mode: {fixture.autonomy.get('mode')}")
        typer.echo(f"  max_total_runs: {fixture.autonomy.get('max_total_runs')}")
        typer.echo(f"  max_wall_clock_hours: {fixture.autonomy.get('max_wall_clock_hours')}")
        typer.echo("Dry run only; no charter, cycle, or jobs were created.")
        raise typer.Exit(code=0)
    handle = start_pilot(fixture)
    typer.echo(f"Started pilot '{handle.problem_id}' (tier={handle.tier}).")
    typer.echo(f"  charter_id: {handle.charter_id}")
    typer.echo(f"  cycle_id:   {handle.cycle_id}")
    typer.echo("")
    typer.echo("Discovery kickoff was enqueued. Evaluate with:")
    typer.echo(f"  synthetos pilot evaluate {problem_id} {handle.cycle_id}")


@app.command("evaluate")
def evaluate_cmd(
    problem_id: str = typer.Argument(...),
    cycle_id: UUID = typer.Argument(..., help="Cycle UUID returned by 'pilot run'."),
    root: Path = typer.Option(DEFAULT_FIXTURE_ROOT, "--root"),
    write: bool = typer.Option(
        True, "--write/--no-write", help="Persist evaluation to artifacts/pilot/..."
    ),
) -> None:
    """Grade a completed pilot cycle against the fixture's expectations."""
    try:
        fixture = load_fixture(root / problem_id)
    except PilotFixtureError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    result = evaluate_cycle(fixture, cycle_id)
    typer.echo(f"cycle_status: {result.cycle_status}")
    typer.echo(f"passed: {result.passed}")
    for k, v in result.checks.items():
        typer.echo(f"  {k}: {v}")
    for w in result.warnings:
        typer.secho(f"warning: {w}", fg=typer.colors.YELLOW)
    if write:
        json_path, md_path = write_evaluation(fixture, result)
        typer.echo(f"wrote {json_path}")
        typer.echo(f"wrote {md_path}")
    if not result.passed:
        raise typer.Exit(code=1)


@app.command("compare")
def compare_cmd(
    left: str = typer.Argument(..., help="Evaluation JSON path or cycle UUID."),
    right: str = typer.Argument(..., help="Evaluation JSON path or cycle UUID."),
    problem_id: str | None = typer.Option(
        None,
        "--problem-id",
        help="Fixture name to use when left/right are cycle UUIDs instead of files.",
    ),
    root: Path = typer.Option(DEFAULT_FIXTURE_ROOT, "--root"),
    write: bool = typer.Option(
        True,
        "--write/--no-write",
        help="Persist comparison to artifacts/pilot/compare/...",
    ),
) -> None:
    """Diff two pilot evaluations."""
    comparison = compare_evaluations(
        _load_compare_input(left, problem_id=problem_id, root=root),
        _load_compare_input(right, problem_id=problem_id, root=root),
    )
    typer.echo(f"left:  {comparison.left_label}")
    typer.echo(f"right: {comparison.right_label}")
    for key, value in comparison.deltas.items():
        typer.echo(f"  {key}: {value}")
    for line in comparison.summary:
        typer.echo(f"  summary: {line}")

    if write:
        json_path, md_path = write_comparison(comparison)
        typer.echo(f"wrote {json_path}")
        typer.echo(f"wrote {md_path}")


def _load_compare_input(
    raw: str,
    *,
    problem_id: str | None,
    root: Path,
):
    path = Path(raw)
    if path.exists():
        return load_evaluation(path)

    if problem_id is None:
        typer.secho(
            "comparison inputs that are not files require --problem-id",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        cycle_id = UUID(raw)
    except ValueError as exc:
        typer.secho(
            f"comparison input '{raw}' is neither an existing file nor a UUID",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2) from exc

    try:
        fixture = load_fixture(root / problem_id)
    except PilotFixtureError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    return evaluate_cycle(fixture, cycle_id)
