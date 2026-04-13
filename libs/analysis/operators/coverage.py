"""analysis_coverage operator -- coverage verification."""

from __future__ import annotations

from sqlalchemy import select

from libs.analysis.operators._common import (
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
from libs.storage.models.analysis import (
    GraphEdge,
    GraphNode,
    IngestedDocument,
    PaperChunk,
)

log = get_logger("analysis.operators.coverage")


def analysis_coverage_operator(op_input: OperatorInput) -> OperatorResult:
    """Compute coverage diagnostics for the analysis session."""
    result = OperatorResult(success=False)
    session_id = analysis_session_id_from_payload(op_input)

    factory = get_sync_session_factory()
    with factory() as db:
        analysis = load_analysis_session(db, session_id)
        analysis.status = "verifying"
        db.flush()

        # Load all required data
        doc = db.execute(
            select(IngestedDocument).where(
                IngestedDocument.analysis_session_id == session_id,
            )
        ).scalar_one_or_none()

        chunks = list(db.execute(
            select(PaperChunk).where(
                PaperChunk.analysis_session_id == session_id,
            )
        ).scalars().all())

        nodes = list(db.execute(
            select(GraphNode).where(
                GraphNode.analysis_session_id == session_id,
            )
        ).scalars().all())

        edges = list(db.execute(
            select(GraphEdge).where(
                GraphEdge.analysis_session_id == session_id,
            )
        ).scalars().all())

        if doc is None:
            mark_failed(
                analysis, step="coverage",
                error="ingested document not found",
            )
            db.commit()
            result.error = "ingested document not found"
            return result

        try:
            from libs.analysis.coverage_check import compute_coverage

            diagnostic = compute_coverage(
                db,
                doc=doc,
                chunks=chunks,
                nodes=nodes,
                edges=edges,
                analysis_session_id=session_id,
            )
        except Exception as exc:
            mark_failed(analysis, step="coverage", error=str(exc))
            db.commit()
            result.error = str(exc)
            return result

        analysis.status = "coverage_verified"
        append_step_log(
            analysis, step="coverage",
            detail={
                "overall_score": diagnostic.overall_score,
                "warning_count": len(diagnostic.warnings or []),
            },
        )
        merge_stats(analysis, {
            "coverage_score": diagnostic.overall_score,
            "coverage_warning_count": len(diagnostic.warnings or []),
        })

        emit_event_sync(
            db,
            event_type=AnalysisEvents.coverage_computed,
            charter_id=analysis.charter_id,
            cycle_id=analysis.cycle_id,
            payload={
                "analysis_session_id": str(session_id),
                "overall_score": diagnostic.overall_score,
                "warning_count": len(diagnostic.warnings or []),
            },
        )

        enqueue_next(
            db,
            cycle_id=analysis.cycle_id,
            next_job_type="analysis_review",
            analysis_session_id=session_id,
        )
        db.commit()

    result.success = True
    result.summary = f"Coverage score: {diagnostic.overall_score:.2f}"
    return result
