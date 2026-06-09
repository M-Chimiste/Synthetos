"""Goal-oriented research commands."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import typer
from sqlalchemy import select

from libs.core.services.goal_service import create_goal_sync, read_goal_report_file, stop_goal_sync
from libs.schemas.goals import GoalCreate, GoalCriterion, GoalPolicy
from libs.storage.base import get_sync_session_factory
from libs.storage.models.goals import GoalAttempt, ResearchGoal

app = typer.Typer(help="Manage goal-oriented research loops.")


@app.command("create")
def create_goal(
    charter_id: UUID = typer.Option(..., "--charter-id"),
    title: str = typer.Option(..., "--title"),
    statement: str = typer.Option(..., "--statement"),
    criteria_json: Path | None = typer.Option(
        None,
        "--criteria-json",
        help="JSON file containing a list of success criteria.",
    ),
    policy_json: Path | None = typer.Option(
        None,
        "--policy-json",
        help="JSON file containing goal policy overrides.",
    ),
) -> None:
    criteria = _load_criteria(criteria_json)
    policy = _load_policy(policy_json)
    body = GoalCreate(
        charter_id=charter_id,
        title=title,
        goal_statement=statement,
        success_criteria=criteria,
        policy=policy,
    )
    factory = get_sync_session_factory()
    with factory() as db:
        goal = create_goal_sync(db, body)
        db.commit()
        typer.echo(f"Created goal {goal.id}")


@app.command("show")
def show_goal(goal_id: UUID = typer.Argument(...)) -> None:
    factory = get_sync_session_factory()
    with factory() as db:
        goal = db.get(ResearchGoal, goal_id)
        if goal is None:
            typer.echo(f"Goal {goal_id} not found", err=True)
            raise typer.Exit(1)
        typer.echo(f"ID:        {goal.id}")
        typer.echo(f"Charter:   {goal.charter_id}")
        typer.echo(f"Title:     {goal.title}")
        typer.echo(f"Status:    {goal.status}")
        typer.echo(f"Statement: {goal.goal_statement}")
        typer.echo(f"Report:    {goal.report_path or '—'}")


@app.command("attempts")
def list_attempts(goal_id: UUID = typer.Argument(...)) -> None:
    factory = get_sync_session_factory()
    with factory() as db:
        rows = db.execute(
            select(GoalAttempt)
            .where(GoalAttempt.goal_id == goal_id)
            .order_by(GoalAttempt.attempt_number)
        ).scalars()
        for attempt in rows:
            typer.echo(
                f"#{attempt.attempt_number:<3} {attempt.status:<10} "
                f"cycle={attempt.cycle_id} report={attempt.report_path or '—'}"
            )


@app.command("report")
def show_report(goal_id: UUID = typer.Argument(...)) -> None:
    factory = get_sync_session_factory()
    with factory() as db:
        goal = db.get(ResearchGoal, goal_id)
        if goal is None:
            typer.echo(f"Goal {goal_id} not found", err=True)
            raise typer.Exit(1)
        markdown, _json_payload = read_goal_report_file(goal)
        if markdown is None:
            typer.echo("Goal report has not been generated yet.", err=True)
            raise typer.Exit(1)
        typer.echo(markdown)


@app.command("stop")
def stop_goal(goal_id: UUID = typer.Argument(...)) -> None:
    factory = get_sync_session_factory()
    with factory() as db:
        goal = stop_goal_sync(db, goal_id)
        db.commit()
        typer.echo(f"Stopped goal {goal.id}")


def _load_criteria(path: Path | None) -> list[GoalCriterion]:
    if path is None:
        return [
            GoalCriterion(
                name="completed run",
                description="At least one experiment run completed successfully.",
                check_type="completed_run_exists",
            ),
            GoalCriterion(
                name="cycle report",
                description="A cycle report was generated.",
                check_type="report_generated",
            ),
        ]
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [GoalCriterion.model_validate(item) for item in raw]


def _load_policy(path: Path | None) -> GoalPolicy:
    if path is None:
        return GoalPolicy()
    return GoalPolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))
