"""Discovery pipeline CLI commands.

Convenience wrapper for headless testing without the web UI:

    synthetos discovery run --charter-id <uuid> --query "..."
"""

from __future__ import annotations

import time
from uuid import UUID

import typer
import uuid_utils
from sqlalchemy import select

from libs.core.clock import utcnow
from libs.core.types import CycleStatus, JobStatus
from libs.schemas.discovery import (
    DiscoveryBudget,
    ProblemProfileCreate,
    RerankPolicy,
)
from libs.storage.base import get_sync_session_factory
from libs.storage.models.discovery import DiscoverySession, ProblemProfile
from libs.storage.models.jobs import Job
from libs.storage.models.papers import PaperCard
from libs.storage.models.research import ResearchCharter, ResearchCycle

app = typer.Typer(help="Run discovery sessions from the CLI.")


def _ensure_cycle(session, charter_id: UUID) -> ResearchCycle:
    cycles = (
        session.execute(
            select(ResearchCycle)
            .where(ResearchCycle.charter_id == charter_id)
            .order_by(ResearchCycle.created_at.desc())
        )
        .scalars()
        .all()
    )
    for c in cycles:
        if c.status in (CycleStatus.created.value, CycleStatus.discovery_ready.value):
            return c
    cycle = ResearchCycle(
        id=uuid_utils.uuid7(),
        charter_id=charter_id,
        status=CycleStatus.created,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(cycle)
    session.flush()
    return cycle


@app.command("run")
def run(
    charter_id: str = typer.Option(..., "--charter-id", help="Charter UUID"),
    query: str = typer.Option(..., "--query", help="Problem statement / query text"),
    notes: str = typer.Option("", "--notes"),
    view: str = typer.Option("both", "--view", help="stable | discovery | both"),
    rerank: bool = typer.Option(True, "--rerank/--no-rerank"),
    rerank_top_n: int = typer.Option(100, "--rerank-top-n"),
    rerank_budget_seconds: float = typer.Option(30.0, "--rerank-budget-seconds"),
    internal_top_k: int = typer.Option(200, "--internal-top-k"),
    external_top_k: int = typer.Option(50, "--external-top-k"),
    analyze_top_n: int = typer.Option(25, "--analyze-top-n"),
    no_external: bool = typer.Option(False, "--no-external", help="Skip arxiv_live"),
    wait: bool = typer.Option(True, "--wait/--no-wait"),
) -> None:
    """Create a charter-scoped discovery session and enqueue the operator chain."""
    try:
        cid = UUID(charter_id)
    except ValueError as exc:
        typer.echo(f"Invalid charter id: {charter_id}", err=True)
        raise typer.Exit(code=1) from exc

    factory = get_sync_session_factory()
    with factory() as session:
        charter = session.get(ResearchCharter, cid)
        if charter is None:
            typer.echo(f"Charter {cid} not found", err=True)
            raise typer.Exit(code=1)

        cycle = _ensure_cycle(session, cid)

        existing = session.execute(
            select(ProblemProfile).where(ProblemProfile.cycle_id == cycle.id)
        ).scalar_one_or_none()
        if existing is not None:
            typer.echo(
                f"Cycle {cycle.id} already has a problem profile; "
                f"create a new cycle to run another discovery session.",
                err=True,
            )
            raise typer.Exit(code=1)

        body = ProblemProfileCreate(
            query_text=query,
            notes=notes,
            source_scope={
                "internal_corpus": True,
                "arxiv_live": not no_external,
            },
            view_preference=view,
            rerank_policy=RerankPolicy(
                enabled=rerank,
                top_n=rerank_top_n,
                budget_seconds=rerank_budget_seconds,
            ),
            budget=DiscoveryBudget(
                max_internal_results=internal_top_k,
                max_external_results=0 if no_external else external_top_k,
                analyze_top_n=analyze_top_n,
            ),
        )

        profile = ProblemProfile(
            id=uuid_utils.uuid7(),
            cycle_id=cycle.id,
            query_text=body.query_text,
            notes=body.notes,
            source_scope=body.source_scope,
            view_preference=body.view_preference,
            rerank_policy=body.rerank_policy.model_dump(),
            budget=body.budget.model_dump(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(profile)
        session.flush()

        discovery = DiscoverySession(
            id=uuid_utils.uuid7(),
            cycle_id=cycle.id,
            charter_id=cid,
            profile_id=profile.id,
            status="created",
            view=body.view_preference,
            stats={},
            step_log=[],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(discovery)

        job = Job(
            id=uuid_utils.uuid7(),
            cycle_id=cycle.id,
            job_type="discovery_intake",
            status=JobStatus.pending,
            payload={"session_id": str(discovery.id)},
            priority=10,
            created_at=utcnow(),
        )
        session.add(job)
        session.commit()

        typer.echo(f"Created discovery session {discovery.id} on cycle {cycle.id}")
        typer.echo(f"Enqueued discovery_intake job {job.id}")

    if not wait:
        return

    typer.echo("Waiting for the operator chain to complete (Ctrl-C to detach) ...")
    last_status = None
    while True:
        with factory() as session:
            current = session.get(DiscoverySession, discovery.id)
            if current is None:
                typer.echo("session vanished from DB")
                return
            if current.status != last_status:
                typer.echo(f"  status: {current.status}")
                last_status = current.status
            if current.status == "completed":
                typer.echo(f"Done. Report at: {current.report_artifact_path}")
                count = session.execute(
                    select(PaperCard).where(PaperCard.session_id == discovery.id)
                ).all()
                typer.echo(f"Persisted {len(count)} paper cards")
                return
            if current.error:
                typer.echo(f"FAILED: {current.error}", err=True)
                raise typer.Exit(code=1)
        time.sleep(2.0)
