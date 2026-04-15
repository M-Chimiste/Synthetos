"""CLI commands for Phase 2 paper analysis."""

from __future__ import annotations

import asyncio
from uuid import UUID

import typer
from sqlalchemy import select

from libs.core.logging import get_logger

app = typer.Typer(help="Paper analysis commands")
log = get_logger("cli.analysis")


@app.command("run")
def run_analysis(
    paper_id: str = typer.Option(..., "--paper-id", help="UUID of the paper card"),
    charter_id: str = typer.Option(..., "--charter-id", help="UUID of the charter"),
    cycle_id: str = typer.Option(..., "--cycle-id", help="UUID of the cycle"),
) -> None:
    """Start full-text analysis on a shortlisted paper."""
    asyncio.run(_start_analysis(UUID(paper_id), UUID(charter_id), UUID(cycle_id)))


async def _start_analysis(paper_id: UUID, charter_id: UUID, cycle_id: UUID) -> None:
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        from libs.core.services.analysis_service import (
            AnalysisServiceError,
            start_analysis,
        )

        try:
            session_read, job_id = await start_analysis(
                db,
                paper_card_id=paper_id,
                charter_id=charter_id,
                cycle_id=cycle_id,
            )
            await db.commit()
            typer.echo(
                f"Analysis session {session_read.id} created. "
                f"Ingest job: {job_id}"
            )
        except AnalysisServiceError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc


@app.command("status")
def analysis_status(
    paper_id: str = typer.Option(..., "--paper-id", help="UUID of the paper card"),
) -> None:
    """Check analysis status for a paper."""
    asyncio.run(_show_status(UUID(paper_id)))


async def _show_status(paper_id: UUID) -> None:
    from libs.storage.base import get_async_session
    from libs.storage.models.analysis import AnalysisSession

    async with get_async_session() as db:
        result = await db.execute(
            select(AnalysisSession)
            .where(AnalysisSession.paper_card_id == paper_id)
            .order_by(AnalysisSession.created_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session is None:
            typer.echo("No analysis session found for this paper.")
            return
        typer.echo(f"Session: {session.id}")
        typer.echo(f"Status:  {session.status}")
        if session.error:
            typer.echo(f"Error:   {session.error}")
        if session.stats:
            typer.echo(f"Stats:   {session.stats}")


@app.command("document")
def show_document(
    session_id: str = typer.Option(..., "--session-id", help="UUID of the analysis session"),
) -> None:
    """Show a summary of the ingested full-text artifact."""
    asyncio.run(_show_document(UUID(session_id)))


async def _show_document(session_id: UUID) -> None:
    from libs.core.services.analysis_service import get_ingested_document
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        doc = await get_ingested_document(db, session_id)
        if doc is None:
            typer.echo("No ingested document found for this session.")
            return
        typer.echo(f"Session:        {doc.analysis_session_id}")
        typer.echo(f"Paper:          {doc.paper_card_id}")
        typer.echo(f"Fetch method:   {doc.fetch_method}")
        typer.echo(f"Source URL:     {doc.source_url}")
        typer.echo(f"Content hash:   {doc.content_hash}")
        typer.echo(f"Sections:       {len(doc.normalized_sections or [])}")
        typer.echo(f"Figures:        {len(doc.normalized_figures or [])}")
        typer.echo(f"Tables:         {len(doc.normalized_tables or [])}")
        typer.echo(f"Equations:      {len(doc.normalized_equations or [])}")
        typer.echo(f"Quality:        {(doc.quality_assessment or {}).get('quality_score')}")


@app.command("list")
def list_sessions(
    charter_id: str = typer.Option(..., "--charter-id", help="UUID of the charter"),
) -> None:
    """List analysis sessions for a charter."""
    asyncio.run(_list_sessions(UUID(charter_id)))


async def _list_sessions(charter_id: UUID) -> None:
    from libs.core.services.analysis_service import list_analysis_sessions
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        items, total = await list_analysis_sessions(
            db, charter_id=charter_id, limit=20,
        )
        typer.echo(f"Total: {total}")
        for s in items:
            typer.echo(f"  {s.id}  {s.status:20s}  paper={s.paper_card_id}")


@app.command("evidence")
def list_evidence(
    charter_id: str = typer.Option(..., "--charter-id", help="UUID of the charter"),
) -> None:
    """List evidence cards for a charter."""
    asyncio.run(_list_evidence(UUID(charter_id)))


async def _list_evidence(charter_id: UUID) -> None:
    from libs.core.services.analysis_service import list_evidence_cards
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        items, total = await list_evidence_cards(
            db, charter_id=charter_id, limit=20,
        )
        typer.echo(f"Total: {total}")
        for e in items:
            typer.echo(
                f"  {e.id}  [{e.evidence_type}]  "
                f"conf={e.confidence:.2f}  {e.claim[:80]}"
            )


@app.command("qa")
def ask_question(
    paper_id: str = typer.Option(..., "--paper-id", help="UUID of the paper card"),
    question: str = typer.Option(..., "--question", help="Question to ask about the paper"),
) -> None:
    """Run graph-aware QA for the latest completed analysis session of a paper."""
    asyncio.run(_ask_question(UUID(paper_id), question))


async def _ask_question(paper_id: UUID, question: str) -> None:
    from libs.core.services.analysis_service import run_qa
    from libs.storage.base import get_async_session

    async with get_async_session() as db:
        response = await run_qa(
            db,
            paper_card_id=paper_id,
            question=question,
            max_chunks=10,
            expand_graph=True,
        )
        typer.echo(response.answer)
        if response.supporting_chunks:
            typer.echo("\nSupporting chunks:")
            for chunk in response.supporting_chunks[:5]:
                typer.echo(
                    f"  - {chunk.chunk_id} [{chunk.section_path or 'chunk'}] "
                    f"{(chunk.snippet or '')[:120]}"
                )
