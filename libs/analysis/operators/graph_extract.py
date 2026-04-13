"""analysis_graph_extract operator -- LLM-driven typed graph extraction."""

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
from libs.storage.models.analysis import PaperChunk

log = get_logger("analysis.operators.graph_extract")


def analysis_graph_extract_operator(op_input: OperatorInput) -> OperatorResult:
    """Extract typed graph from paper chunks."""
    result = OperatorResult(success=False)
    session_id = analysis_session_id_from_payload(op_input)

    factory = get_sync_session_factory()
    with factory() as db:
        analysis = load_analysis_session(db, session_id)
        analysis.status = "extracting"
        db.flush()

        # Load chunks
        chunks = db.execute(
            select(PaperChunk)
            .where(PaperChunk.analysis_session_id == session_id)
            .order_by(PaperChunk.ordinal)
        ).scalars().all()

        if not chunks:
            mark_failed(
                analysis, step="graph_extract", error="no chunks found",
            )
            db.commit()
            result.error = "no chunks found"
            return result

        try:
            from libs.analysis.graph_extraction import (
                extract_graph,
                project_to_graph_adapter,
            )
            from libs.core.config import get_settings

            nodes, edges = asyncio.run(
                extract_graph(
                    db,
                    chunks=list(chunks),
                    analysis_session_id=session_id,
                    paper_card_id=analysis.paper_card_id,
                    concurrency=int(
                        analysis_budget(analysis).get("graph_extraction_concurrency", 4)
                    ),
                )
            )

            # Project to AGE if available
            graph_name = f"paper_{str(analysis.paper_card_id)[:8]}"
            settings = get_settings()
            asyncio.run(
                project_to_graph_adapter(
                    nodes, edges, graph_name, settings.sync_db_url,
                )
            )
        except Exception as exc:
            mark_failed(analysis, step="graph_extract", error=str(exc))
            db.commit()
            result.error = str(exc)
            return result

        # Count by type
        node_types: dict[str, int] = {}
        for n in nodes:
            node_types[n.node_type] = node_types.get(n.node_type, 0) + 1
        edge_types: dict[str, int] = {}
        for e in edges:
            edge_types[e.edge_type] = edge_types.get(e.edge_type, 0) + 1

        analysis.status = "graph_extracted"
        append_step_log(
            analysis, step="graph_extract",
            detail={
                "node_count": len(nodes),
                "edge_count": len(edges),
                "node_types": node_types,
                "edge_types": edge_types,
            },
        )
        merge_stats(analysis, {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_types": node_types,
            "edge_types": edge_types,
        })

        emit_event_sync(
            db,
            event_type=AnalysisEvents.graph_extracted,
            charter_id=analysis.charter_id,
            cycle_id=analysis.cycle_id,
            payload={
                "analysis_session_id": str(session_id),
                "node_count": len(nodes),
                "edge_count": len(edges),
                "node_types": node_types,
                "edge_types": edge_types,
            },
        )

        enqueue_next(
            db,
            cycle_id=analysis.cycle_id,
            next_job_type="analysis_coverage",
            analysis_session_id=session_id,
        )
        db.commit()

    result.success = True
    result.summary = f"Extracted {len(nodes)} nodes, {len(edges)} edges"
    return result
