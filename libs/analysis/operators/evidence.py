"""analysis_evidence operator -- extract evidence cards (terminal operator)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from libs.analysis.operators._common import (
    analysis_budget,
    analysis_session_id_from_payload,
    append_step_log,
    load_analysis_session,
    mark_failed,
    merge_stats,
)
from libs.core.event_types import AnalysisEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.state_machine import validate_transition
from libs.core.types import CycleStatus
from libs.storage.base import get_sync_session_factory
from libs.storage.models.analysis import GraphNode, PaperAnalysisPacket, PaperChunk
from libs.storage.models.papers import PaperCard
from libs.storage.models.research import ResearchCycle

log = get_logger("analysis.operators.evidence")


def analysis_evidence_operator(op_input: OperatorInput) -> OperatorResult:
    """Extract evidence cards from the analysis packet. Terminal operator."""
    result = OperatorResult(success=False)
    session_id = analysis_session_id_from_payload(op_input)

    factory = get_sync_session_factory()
    with factory() as db:
        analysis = load_analysis_session(db, session_id)
        analysis.status = "evidence_extracting"
        db.flush()

        # Load analysis packet
        packet = db.execute(
            select(PaperAnalysisPacket).where(
                PaperAnalysisPacket.analysis_session_id == session_id,
            )
        ).scalar_one_or_none()

        if packet is None:
            mark_failed(
                analysis, step="evidence",
                error="analysis packet not found",
            )
            db.commit()
            result.error = "analysis packet not found"
            return result

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

        try:
            from libs.analysis.evidence_extraction import extract_evidence

            cards = asyncio.run(
                extract_evidence(
                    db,
                    packet=packet,
                    chunks=chunks,
                    nodes=nodes,
                    charter_id=analysis.charter_id,
                    cycle_id=analysis.cycle_id,
                    concurrency=int(
                        analysis_budget(analysis).get("evidence_extraction_concurrency", 4)
                    ),
                )
            )
        except Exception as exc:
            mark_failed(analysis, step="evidence", error=str(exc))
            db.commit()
            result.error = str(exc)
            return result

        # Count contradictions
        contradiction_count = sum(
            1 for c in cards
            if c.contradiction_flags and c.contradiction_flags.get("contradicts")
        )
        redundancy_count = sum(
            1 for c in cards if c.redundancy_group
        )

        # Update paper card status
        paper = db.execute(
            select(PaperCard).where(PaperCard.id == analysis.paper_card_id)
        ).scalar_one_or_none()
        if paper:
            paper.analysis_status = "analyzed"

        cycle = db.get(ResearchCycle, analysis.cycle_id)
        if cycle is not None and cycle.status == CycleStatus.analysis_ready.value:
            validate_transition(
                CycleStatus.analysis_ready,
                CycleStatus.evidence_ready,
            )
            cycle.status = CycleStatus.evidence_ready

        # Mark session completed
        from libs.core.clock import utcnow

        analysis.status = "completed"
        analysis.completed_at = utcnow()
        append_step_log(
            analysis, step="evidence",
            detail={
                "card_count": len(cards),
                "contradiction_count": contradiction_count,
                "redundancy_count": redundancy_count,
            },
        )
        merge_stats(analysis, {
            "evidence_card_count": len(cards),
            "contradiction_count": contradiction_count,
            "redundancy_count": redundancy_count,
        })

        # Emit evidence extracted event
        emit_event_sync(
            db,
            event_type=AnalysisEvents.evidence_extracted,
            charter_id=analysis.charter_id,
            cycle_id=analysis.cycle_id,
            payload={
                "analysis_session_id": str(session_id),
                "card_count": len(cards),
                "contradiction_count": contradiction_count,
                "redundancy_count": redundancy_count,
            },
        )

        # Emit session completed event
        emit_event_sync(
            db,
            event_type=AnalysisEvents.session_completed,
            charter_id=analysis.charter_id,
            cycle_id=analysis.cycle_id,
            payload={
                "analysis_session_id": str(session_id),
                "paper_card_id": str(analysis.paper_card_id),
            },
        )

        # Terminal operator -- no enqueue_next
        db.commit()

    result.success = True
    result.summary = (
        f"Extracted {len(cards)} evidence cards "
        f"({contradiction_count} contradictions, {redundancy_count} redundancies)"
    )
    return result
