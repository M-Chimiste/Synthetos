"""analysis_ingest operator -- fetch full text and persist IngestedDocument."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from libs.analysis.operators._common import (
    analysis_budget,
    analysis_session_id_from_payload,
    append_step_log,
    enqueue_next,
    load_analysis_session,
    mark_failed,
    mark_started_if_needed,
    merge_stats,
)
from libs.core.event_types import AnalysisEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.storage.base import get_sync_session_factory
from libs.storage.models.papers import PaperCard

log = get_logger("analysis.operators.ingest")


def analysis_ingest_operator(op_input: OperatorInput) -> OperatorResult:
    """Fetch full text for a paper and persist the ingested document."""
    result = OperatorResult(success=False)
    session_id = analysis_session_id_from_payload(op_input)

    factory = get_sync_session_factory()
    with factory() as db:
        analysis = load_analysis_session(db, session_id)
        mark_started_if_needed(analysis)
        analysis.status = "ingesting"
        db.flush()

        # Load the paper card
        paper = db.execute(
            select(PaperCard).where(PaperCard.id == analysis.paper_card_id)
        ).scalar_one_or_none()

        if paper is None:
            mark_failed(
                analysis, step="ingest", error="paper card not found",
            )
            db.commit()
            result.error = "paper card not found"
            return result

        paper_url = paper.source_url or ""
        pdf_url = paper.pdf_url

        if not paper_url and not pdf_url:
            mark_failed(
                analysis, step="ingest", error="no URL available for paper",
            )
            db.commit()
            result.error = "no URL available for paper"
            return result

        try:
            from libs.analysis.ingestion import fetch_and_persist

            budget = analysis_budget(analysis)
            doc = asyncio.run(
                fetch_and_persist(
                    db,
                    analysis_session_id=session_id,
                    paper_card_id=analysis.paper_card_id,
                    paper_url=paper_url,
                    pdf_url=pdf_url,
                    quality_threshold=float(budget.get("html_quality_threshold", 0.5)),
                )
            )
        except Exception as exc:
            mark_failed(
                analysis, step="ingest", error=str(exc),
            )
            db.commit()
            result.error = str(exc)
            return result

        # Update session
        analysis.status = "ingested"
        append_step_log(
            analysis, step="ingest",
            detail={
                "fetch_method": doc.fetch_method,
                "content_hash": doc.content_hash,
                "quality_score": (doc.quality_assessment or {}).get("quality_score"),
            },
        )
        merge_stats(analysis, {
            "fetch_method": doc.fetch_method,
            "content_hash": doc.content_hash,
        })

        # Update paper card status
        paper.analysis_status = "analyzing"

        # Emit event
        emit_event_sync(
            db,
            event_type=AnalysisEvents.paper_ingested,
            charter_id=analysis.charter_id,
            cycle_id=analysis.cycle_id,
            payload={
                "analysis_session_id": str(session_id),
                "paper_card_id": str(analysis.paper_card_id),
                "fetch_method": doc.fetch_method,
                "quality_score": (doc.quality_assessment or {}).get("quality_score"),
            },
        )

        # Enqueue next
        enqueue_next(
            db,
            cycle_id=analysis.cycle_id,
            next_job_type="analysis_chunk",
            analysis_session_id=session_id,
        )

        db.commit()

    result.success = True
    result.summary = f"Ingested paper via {doc.fetch_method}"
    return result
