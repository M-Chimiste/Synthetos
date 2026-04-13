"""analysis_chunk operator -- structure-aware chunking + embedding."""

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
    merge_stats,
)
from libs.core.event_types import AnalysisEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.storage.base import get_sync_session_factory
from libs.storage.models.analysis import IngestedDocument

log = get_logger("analysis.operators.chunk")


def analysis_chunk_operator(op_input: OperatorInput) -> OperatorResult:
    """Chunk the ingested document and embed chunks."""
    result = OperatorResult(success=False)
    session_id = analysis_session_id_from_payload(op_input)

    factory = get_sync_session_factory()
    with factory() as db:
        analysis = load_analysis_session(db, session_id)
        analysis.status = "chunking"
        db.flush()

        # Load ingested document
        doc = db.execute(
            select(IngestedDocument).where(
                IngestedDocument.analysis_session_id == session_id,
            )
        ).scalar_one_or_none()

        if doc is None:
            mark_failed(
                analysis, step="chunk", error="ingested document not found",
            )
            db.commit()
            result.error = "ingested document not found"
            return result

        try:
            from libs.analysis.chunking import chunk_document, embed_chunks

            budget = analysis_budget(analysis)
            chunks = chunk_document(
                db,
                doc=doc,
                analysis_session_id=session_id,
                paper_card_id=analysis.paper_card_id,
                max_chunks=int(budget.get("max_chunks", 500)),
            )

            # Embed chunks
            embedded_count = asyncio.run(embed_chunks(chunks, db))
        except Exception as exc:
            mark_failed(analysis, step="chunk", error=str(exc))
            db.commit()
            result.error = str(exc)
            return result

        # Count by type
        type_counts: dict[str, int] = {}
        for c in chunks:
            type_counts[c.chunk_type] = type_counts.get(c.chunk_type, 0) + 1

        analysis.status = "chunked"
        append_step_log(
            analysis, step="chunk",
            detail={"chunk_count": len(chunks), "type_counts": type_counts},
        )
        merge_stats(analysis, {
            "chunk_count": len(chunks),
            "chunk_type_counts": type_counts,
            "embedded_count": embedded_count,
        })

        emit_event_sync(
            db,
            event_type=AnalysisEvents.paper_chunked,
            charter_id=analysis.charter_id,
            cycle_id=analysis.cycle_id,
            payload={
                "analysis_session_id": str(session_id),
                "chunk_count": len(chunks),
                "type_counts": type_counts,
            },
        )

        enqueue_next(
            db,
            cycle_id=analysis.cycle_id,
            next_job_type="analysis_graph_extract",
            analysis_session_id=session_id,
        )
        db.commit()

    result.success = True
    result.summary = f"Created {len(chunks)} chunks ({embedded_count} embedded)"
    return result
