"""analysis_review operator -- generate PaperAnalysisPacket + PaperReviewArtifact."""

from __future__ import annotations

import asyncio
from collections import Counter

from sqlalchemy import select
from uuid_utils import uuid7

from libs.adapters.llm.router import ModelRouter
from libs.analysis.operators._common import (
    analysis_session_id_from_payload,
    append_step_log,
    enqueue_next,
    load_analysis_session,
    mark_failed,
    merge_stats,
)
from libs.analysis.reports import (
    build_report_paths,
    render_json,
    render_markdown,
    write_report_bundle,
)
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.event_types import AnalysisEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.schemas.model_gateway import ModelRole
from libs.storage.base import get_sync_session_factory
from libs.storage.models.analysis import (
    CoverageDiagnostic,
    GraphEdge,
    GraphNode,
    PaperAnalysisPacket,
    PaperChunk,
)

log = get_logger("analysis.operators.review")


def analysis_review_operator(op_input: OperatorInput) -> OperatorResult:
    """Generate analysis packet and review artifact via LLM."""
    result = OperatorResult(success=False)
    session_id = analysis_session_id_from_payload(op_input)

    factory = get_sync_session_factory()
    with factory() as db:
        analysis = load_analysis_session(db, session_id)
        analysis.status = "reviewing"
        db.flush()

        # Load data
        chunks = list(db.execute(
            select(PaperChunk)
            .where(PaperChunk.analysis_session_id == session_id)
            .order_by(PaperChunk.ordinal)
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

        coverage = db.execute(
            select(CoverageDiagnostic).where(
                CoverageDiagnostic.analysis_session_id == session_id,
            )
        ).scalar_one_or_none()

        try:
            # Generate summary and analysis packet via LLM
            router = ModelRouter()

            # Build context from chunks and nodes
            chunk_summary = "\n".join(
                f"[{c.section_path or c.chunk_type}] {c.content[:300]}"
                for c in chunks[:15]
            )
            node_summary = "\n".join(
                f"- [{n.node_type}] {n.label}: {n.description or ''}"
                for n in nodes[:20]
            )

            summary_resp = asyncio.run(
                router.complete(
                    ModelRole.paper_analysis,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Summarize this research paper based on the "
                                "extracted chunks and entities. Include key "
                                "contributions, methods, and findings."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Chunks:\n{chunk_summary}\n\n"
                                f"Entities:\n{node_summary}"
                            ),
                        },
                    ],
                )
            )

            # Build graph summary counts
            node_type_counts = dict(Counter(n.node_type for n in nodes))
            edge_type_counts = dict(Counter(e.edge_type for e in edges))
            graph_summary = {
                "node_counts": node_type_counts,
                "edge_counts": edge_type_counts,
            }

            coverage_snapshot = None
            if coverage:
                coverage_snapshot = {
                    "overall_score": coverage.overall_score,
                    "section_coverage": coverage.section_coverage,
                    "figure_coverage": coverage.figure_coverage,
                    "table_coverage": coverage.table_coverage,
                    "warnings": coverage.warnings,
                }

            # Extract key contributions and methods from nodes
            contributions = [
                n.label for n in nodes
                if n.node_type in ("method", "concept")
            ][:10]
            methods = [
                {"name": n.label, "description": n.description}
                for n in nodes if n.node_type == "method"
            ][:10]
            datasets = [
                {"name": n.label, "description": n.description}
                for n in nodes if n.node_type == "dataset"
            ][:10]

            # Create analysis packet
            packet = PaperAnalysisPacket(
                id=uuid7(),
                analysis_session_id=session_id,
                paper_card_id=analysis.paper_card_id,
                charter_id=analysis.charter_id,
                summary=summary_resp.content,
                key_contributions=contributions,
                methods_used=methods,
                datasets_referenced=datasets,
                reproducibility_notes=None,
                graph_summary=graph_summary,
                coverage_snapshot=coverage_snapshot,
                chunk_count=len(chunks),
                node_count=len(nodes),
                edge_count=len(edges),
                analysis_depth="full",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(packet)
            db.flush()

            # Generate review artifact
            from libs.analysis.paper_review import generate_review

            review = asyncio.run(
                generate_review(db, packet=packet, coverage=coverage)
            )

            paths = build_report_paths(get_settings().data_root, session_id)
            markdown = render_markdown(
                session=analysis,
                packet=packet,
                review=review,
                coverage=coverage,
            )
            json_payload = render_json(
                session=analysis,
                packet=packet,
                review=review,
                coverage=coverage,
            )
            write_report_bundle(paths, markdown=markdown, json_payload=json_payload)
            analysis.report_artifact_path = str(paths.markdown)

        except Exception as exc:
            mark_failed(analysis, step="review", error=str(exc))
            db.commit()
            result.error = str(exc)
            return result

        analysis.status = "reviewed"
        append_step_log(
            analysis, step="review",
            detail={
                "packet_id": str(packet.id),
                "review_id": str(review.id),
                "report_path": analysis.report_artifact_path,
            },
        )
        merge_stats(analysis, {
            "packet_id": str(packet.id),
            "review_id": str(review.id),
            "report_path": analysis.report_artifact_path,
        })

        emit_event_sync(
            db,
            event_type=AnalysisEvents.review_generated,
            charter_id=analysis.charter_id,
            cycle_id=analysis.cycle_id,
            payload={
                "analysis_session_id": str(session_id),
                "packet_id": str(packet.id),
                "review_id": str(review.id),
                "report_path": analysis.report_artifact_path,
            },
        )

        enqueue_next(
            db,
            cycle_id=analysis.cycle_id,
            next_job_type="analysis_evidence",
            analysis_session_id=session_id,
        )
        db.commit()

    result.success = True
    result.summary = "Generated analysis packet and review artifact"
    report_path = analysis.report_artifact_path
    if report_path:
        result.artifacts.append(report_path)
    return result
