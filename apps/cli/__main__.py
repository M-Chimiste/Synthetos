from __future__ import annotations

import json
from typing import Any

import httpx
import typer

from libs.adapters.llm.gateway import ModelGateway
from libs.core.config import get_config
from libs.core.policy import SYSTEM_ACTOR
from libs.orchestration.worker import run_worker_once
from libs.storage.session import get_session_factory, initialize_database

app = typer.Typer(no_args_is_help=True)
cycle_app = typer.Typer()
skills_app = typer.Typer()
models_app = typer.Typer()
worker_app = typer.Typer()
app.add_typer(cycle_app, name="cycle")
app.add_typer(skills_app, name="skills")
app.add_typer(models_app, name="models")
app.add_typer(worker_app, name="worker")


def api_client() -> httpx.Client:
    config = get_config()
    token = config.dev_admin_token
    return httpx.Client(
        base_url=f"http://{config.api_host}:{config.api_port}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )


def echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


@cycle_app.command("create")
def create_cycle(
    title: str,
    problem_statement: str,
    success_criteria: str = "Establish a credible baseline.",
    source_scope: str = "internal+arxiv",
    stop_conditions: str = "Stop when initialization completes.",
    notes: str = "",
) -> None:
    payload = {
        "title": title,
        "problem_statement": problem_statement,
        "success_criteria": {"summary": success_criteria},
        "budget_envelope": {"timebox_hours": 4},
        "source_scope": {"mode": source_scope},
        "stop_conditions": {"summary": stop_conditions},
        "constraints": {"phase": "phase0"},
        "notes": notes or None,
    }
    with api_client() as client:
        response = client.post("/api/v1/cycles", json=payload)
        response.raise_for_status()
        echo_json(response.json())


@cycle_app.command("list")
def list_cycles() -> None:
    with api_client() as client:
        response = client.get("/api/v1/cycles")
        response.raise_for_status()
        echo_json(response.json())


@cycle_app.command("show")
def show_cycle(cycle_id: str) -> None:
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}")
        response.raise_for_status()
        echo_json(response.json())


@cycle_app.command("command")
def command_cycle(cycle_id: str, command: str) -> None:
    with api_client() as client:
        response = client.post(f"/api/v1/cycles/{cycle_id}/commands", json={"command": command})
        response.raise_for_status()
        echo_json(response.json())


@cycle_app.command("start-intake")
def start_intake(cycle_id: str) -> None:
    """Start literature intake for a research cycle."""
    with api_client() as client:
        response = client.post(
            f"/api/v1/cycles/{cycle_id}/commands",
            json={"command": "start_intake"},
        )
        response.raise_for_status()
        echo_json(response.json())


papers_app = typer.Typer()
app.add_typer(papers_app, name="papers")

literature_app = typer.Typer()
app.add_typer(literature_app, name="literature")


@papers_app.command("list")
def list_papers(cycle_id: str, status: str | None = None) -> None:
    """List papers for a research cycle."""
    with api_client() as client:
        params = {"status": status} if status else {}
        response = client.get(f"/api/v1/cycles/{cycle_id}/papers", params=params)
        response.raise_for_status()
        echo_json(response.json())


@papers_app.command("show")
def show_paper(cycle_id: str, paper_id: str) -> None:
    """Show paper detail."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/papers/{paper_id}")
        response.raise_for_status()
        echo_json(response.json())


@literature_app.command("summary")
def literature_summary(cycle_id: str) -> None:
    """Show literature triage summary for a cycle."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/literature")
        response.raise_for_status()
        echo_json(response.json())


@skills_app.command("list")
def list_skills() -> None:
    with api_client() as client:
        response = client.get("/api/v1/skills")
        response.raise_for_status()
        echo_json(response.json())


@models_app.command("probe")
def probe_models() -> None:
    gateway = ModelGateway.from_config(get_config())
    echo_json({"routes": [route.model_dump(mode="json") for route in gateway.probe_all()]})


@worker_app.command("run-once")
def worker_run_once() -> None:
    config = get_config()
    if config.auto_init_db:
        initialize_database(config)
    session_factory = get_session_factory(config)
    with session_factory() as session:
        result = run_worker_once(session, config, SYSTEM_ACTOR)
        session.commit()
        typer.echo(result)


if __name__ == "__main__":
    app()

