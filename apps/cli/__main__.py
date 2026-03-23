from __future__ import annotations

import json
from typing import Any

import httpx
import typer

from libs.adapters.llm.gateway import ModelGateway
from libs.core.config import get_config
from libs.core.policy import SYSTEM_ACTOR
from libs.orchestration.worker import run_worker_once
from libs.retrieval.arxiv_warehouse import ArxivWarehouseService
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
    keywords: str = "",
    categories: str = "cs",
    date_from: str = "",
    date_until: str = "",
    max_results: int = 50,
    fulltext_budget: int = 3,
    stop_conditions: str = "Stop when initialization completes.",
    notes: str = "",
) -> None:
    keyword_list = [item.strip() for item in keywords.split(",") if item.strip()]
    category_list = [item.strip() for item in categories.split(",") if item.strip()]
    payload = {
        "title": title,
        "problem_statement": problem_statement,
        "success_criteria": {"summary": success_criteria},
        "budget_envelope": {"timebox_hours": 4},
        "source_scope": {
            "mode": source_scope,
            "keywords": keyword_list,
            "categories": category_list or ["cs"],
            "date_from": date_from or None,
            "date_until": date_until or None,
            "max_results": max_results,
            "fulltext_budget": {"max_fetches": fulltext_budget},
        },
        "stop_conditions": {"summary": stop_conditions},
        "constraints": {"phase": "phase1"},
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

evidence_app = typer.Typer()
app.add_typer(evidence_app, name="evidence")

hypothesis_app = typer.Typer()
app.add_typer(hypothesis_app, name="hypothesis")

experiment_app = typer.Typer()
run_app = typer.Typer()
app.add_typer(experiment_app, name="experiment")
app.add_typer(run_app, name="run")


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


@papers_app.command("search")
def search_papers(
    query: str,
    limit: int = 20,
    categories: str = "",
    date_from: str = "",
    date_until: str = "",
) -> None:
    params = {
        "query": query,
        "limit": limit,
    }
    if categories:
        params["categories"] = categories
    if date_from:
        params["date_from"] = date_from
    if date_until:
        params["date_until"] = date_until
    with api_client() as client:
        response = client.get("/api/v1/papers/search", params=params)
        response.raise_for_status()
        echo_json(response.json())


@papers_app.command("sync-arxiv")
def sync_arxiv(
    full: bool = False,
    incremental: bool = False,
    background: bool = False,
) -> None:
    config = get_config()
    if config.auto_init_db:
        initialize_database(config)
    mode = "full" if (full or not incremental) else "incremental"

    if background:
        from libs.orchestration.job_queue import enqueue_job

        session_factory = get_session_factory(config)
        with session_factory() as session:
            job = enqueue_job(
                session,
                SYSTEM_ACTOR,
                cycle_id=None,
                operator_name="arxiv_warehouse_sync",
                payload={"mode": mode},
            )
            session.commit()
            echo_json({"job_public_id": job.public_id, "status": "enqueued", "mode": mode})
        return

    warehouse = ArxivWarehouseService(config)
    session_factory = get_session_factory(config)
    with session_factory() as session:
        if mode == "incremental":
            run = warehouse.sync_incremental(session)
        else:
            run = warehouse.sync_full(session)
        echo_json({
            "public_id": run.public_id,
            "mode": run.mode,
            "source": run.source,
            "status": run.status,
            "inserted_count": run.inserted_count,
            "updated_count": run.updated_count,
            "reembedded_count": run.reembedded_count,
            "skipped_count": run.skipped_count,
            "cursor_updated_until": run.cursor_updated_until,
        })


embeddings_app = typer.Typer()
app.add_typer(embeddings_app, name="embeddings")


@embeddings_app.command("warmup")
def warmup_embeddings() -> None:
    """Pre-download and load the embedding model."""
    from libs.adapters.embeddings.sentence_transformers import (
        SentenceTransformerEmbeddingAdapter,
    )

    config = get_config()
    adapter = SentenceTransformerEmbeddingAdapter(config.embedding)
    info = adapter.warmup()
    echo_json(info)


@literature_app.command("summary")
def literature_summary(cycle_id: str) -> None:
    """Show literature triage summary for a cycle."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/literature")
        response.raise_for_status()
        echo_json(response.json())


@evidence_app.command("list")
def list_evidence(cycle_id: str) -> None:
    """List evidence cards for a research cycle."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/evidence")
        response.raise_for_status()
        echo_json(response.json())


@evidence_app.command("show")
def show_evidence(cycle_id: str, evidence_id: str) -> None:
    """Show evidence card detail."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/evidence/{evidence_id}")
        response.raise_for_status()
        echo_json(response.json())


@evidence_app.command("summary")
def evidence_summary(cycle_id: str) -> None:
    """Show evidence summary for a cycle."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/evidence/summary")
        response.raise_for_status()
        echo_json(response.json())


@hypothesis_app.command("list")
def list_hypotheses(cycle_id: str) -> None:
    """List hypotheses for a research cycle."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/hypotheses")
        response.raise_for_status()
        echo_json(response.json())


@hypothesis_app.command("show")
def show_hypothesis(cycle_id: str, hypothesis_id: str) -> None:
    """Show hypothesis detail."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/hypotheses/{hypothesis_id}")
        response.raise_for_status()
        echo_json(response.json())


@hypothesis_app.command("portfolio")
def hypothesis_portfolio(cycle_id: str) -> None:
    """Show hypothesis portfolio for a cycle."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/hypotheses/portfolio")
        response.raise_for_status()
        echo_json(response.json())


@experiment_app.command("list")
def list_experiments(cycle_id: str) -> None:
    """List experiment specs for a research cycle."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/experiment-specs")
        response.raise_for_status()
        echo_json(response.json())


@experiment_app.command("show")
def show_experiment(cycle_id: str, spec_id: str) -> None:
    """Show experiment spec detail."""
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/experiment-specs/{spec_id}")
        response.raise_for_status()
        echo_json(response.json())


@run_app.command("list")
def list_runs(cycle_id: str) -> None:
    with api_client() as client:
        response = client.get(f"/api/v1/cycles/{cycle_id}/runs")
        response.raise_for_status()
        echo_json(response.json())


@run_app.command("show")
def show_run(run_id: str) -> None:
    with api_client() as client:
        response = client.get(f"/api/v1/runs/{run_id}")
        response.raise_for_status()
        echo_json(response.json())


@run_app.command("start")
def start_run(
    spec_id: str,
    execution_profile: str = "cpu-small",
    force_start: bool = False,
) -> None:
    with api_client() as client:
        response = client.post(
            f"/api/v1/experiment-specs/{spec_id}/runs",
            json={"execution_profile": execution_profile, "force_start": force_start},
        )
        response.raise_for_status()
        echo_json(response.json())


@run_app.command("pause")
def pause_run(run_id: str) -> None:
    with api_client() as client:
        response = client.post(f"/api/v1/runs/{run_id}/commands", json={"command": "pause"})
        response.raise_for_status()
        echo_json(response.json())


@run_app.command("cancel")
def cancel_run(run_id: str) -> None:
    with api_client() as client:
        response = client.post(f"/api/v1/runs/{run_id}/commands", json={"command": "cancel"})
        response.raise_for_status()
        echo_json(response.json())


@run_app.command("retry")
def retry_run(run_id: str) -> None:
    with api_client() as client:
        response = client.post(f"/api/v1/runs/{run_id}/commands", json={"command": "retry"})
        response.raise_for_status()
        echo_json(response.json())


@cycle_app.command("start-evidence")
def start_evidence(cycle_id: str) -> None:
    """Start evidence synthesis for a research cycle."""
    with api_client() as client:
        response = client.post(
            f"/api/v1/cycles/{cycle_id}/commands",
            json={"command": "start_evidence"},
        )
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
