"""Async business logic for the Phase 2 analysis API.

These functions are called from :mod:`apps.api.routers.analysis`.  They
start analysis sessions, query analysis artifacts, run QA, and list evidence.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import AnalysisEvents
from libs.core.events import emit_event
from libs.core.types import ActorType, CycleStatus, JobStatus
from libs.schemas.analysis import (
    AnalysisBudget,
    AnalysisReportResponse,
    AnalysisSessionRead,
    CoverageDiagnosticRead,
    EvidenceCardRead,
    GraphEdgeRead,
    GraphNodeRead,
    IngestedDocumentRead,
    LocateResponse,
    PaperAnalysisPacketRead,
    PaperChunkRead,
    PaperReviewArtifactRead,
    QAResponse,
)
from libs.storage.base import get_sync_session_factory
from libs.storage.models.analysis import (
    AnalysisSession,
    CoverageDiagnostic,
    EvidenceCard,
    GraphEdge,
    GraphNode,
    IngestedDocument,
    PaperAnalysisPacket,
    PaperChunk,
    PaperReviewArtifact,
)
from libs.storage.models.jobs import Job
from libs.storage.models.papers import PaperCard
from libs.storage.models.research import ResearchCycle


class AnalysisServiceError(Exception):
    """Raised when an analysis service operation cannot proceed."""


def _analysis_session_read(analysis: AnalysisSession) -> AnalysisSessionRead:
    return AnalysisSessionRead(
        id=UUID(str(analysis.id)),
        cycle_id=UUID(str(analysis.cycle_id)),
        charter_id=UUID(str(analysis.charter_id)),
        paper_card_id=UUID(str(analysis.paper_card_id)),
        status=analysis.status,
        budget=analysis.budget,
        stats=analysis.stats,
        step_log=analysis.step_log,
        report_artifact_path=analysis.report_artifact_path,
        error=analysis.error,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
    )


# ---------------------------------------------------------------------------
# Start analysis
# ---------------------------------------------------------------------------


async def start_analysis(
    session: AsyncSession,
    *,
    paper_card_id: UUID,
    charter_id: UUID,
    cycle_id: UUID,
    budget: AnalysisBudget | None = None,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> tuple[AnalysisSessionRead, UUID]:
    """Create an analysis session and enqueue ``analysis_ingest``.

    Returns ``(session_read, ingest_job_id)``.
    """
    # Validate paper exists and is eligible
    paper = await session.get(PaperCard, paper_card_id)
    if paper is None:
        raise AnalysisServiceError(f"paper card {paper_card_id} not found")
    if paper.triage_status not in ("shortlisted", "escalated"):
        raise AnalysisServiceError(
            f"paper {paper_card_id} triage_status is {paper.triage_status!r}; "
            "only shortlisted or escalated papers can be analyzed"
        )

    # Ensure cycle exists
    cycle = await session.get(ResearchCycle, cycle_id)
    if cycle is None:
        raise AnalysisServiceError(f"cycle {cycle_id} not found")

    # Transition cycle to analysis_ready if needed
    if cycle.status in (
        CycleStatus.discovery_screened.value,
        CycleStatus.analysis_ready.value,
    ):
        cycle.status = CycleStatus.analysis_ready
        cycle.updated_at = utcnow()

    analysis = AnalysisSession(
        id=uuid7(),
        cycle_id=cycle_id,
        charter_id=charter_id,
        paper_card_id=paper_card_id,
        status="created",
        budget=(budget or AnalysisBudget()).model_dump(),
        stats={},
        step_log=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(analysis)
    await session.flush()

    ingest_job_id = uuid7()
    job = Job(
        id=ingest_job_id,
        cycle_id=cycle_id,
        job_type="analysis_ingest",
        status=JobStatus.pending,
        payload={"analysis_session_id": str(analysis.id)},
        priority=10,
        created_at=utcnow(),
    )
    session.add(job)

    await emit_event(
        session,
        event_type=AnalysisEvents.session_started.value,
        charter_id=charter_id,
        cycle_id=cycle_id,
        payload={
            "analysis_session_id": str(analysis.id),
            "paper_card_id": str(paper_card_id),
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return (
        _analysis_session_read(analysis),
        UUID(str(ingest_job_id)),
    )


# ---------------------------------------------------------------------------
# Session queries
# ---------------------------------------------------------------------------


async def get_analysis_session(
    session: AsyncSession,
    session_id: UUID,
) -> AnalysisSessionRead | None:
    obj = await session.get(AnalysisSession, session_id)
    return _analysis_session_read(obj) if obj else None


async def list_analysis_sessions(
    session: AsyncSession,
    *,
    charter_id: UUID | None = None,
    cycle_id: UUID | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[AnalysisSessionRead], int]:
    query = select(AnalysisSession)
    count_query = select(func.count(AnalysisSession.id))

    if charter_id is not None:
        query = query.where(AnalysisSession.charter_id == charter_id)
        count_query = count_query.where(AnalysisSession.charter_id == charter_id)
    if cycle_id is not None:
        query = query.where(AnalysisSession.cycle_id == cycle_id)
        count_query = count_query.where(AnalysisSession.cycle_id == cycle_id)
    if status is not None:
        query = query.where(AnalysisSession.status == status)
        count_query = count_query.where(AnalysisSession.status == status)

    total = (await session.execute(count_query)).scalar() or 0

    result = await session.execute(
        query.order_by(AnalysisSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [_analysis_session_read(s) for s in result.scalars().all()]
    return items, total


# ---------------------------------------------------------------------------
# Ingested document
# ---------------------------------------------------------------------------


async def get_ingested_document(
    session: AsyncSession,
    analysis_session_id: UUID,
) -> IngestedDocumentRead | None:
    result = await session.execute(
        select(IngestedDocument).where(
            IngestedDocument.analysis_session_id == analysis_session_id,
        )
    )
    obj = result.scalar_one_or_none()
    return IngestedDocumentRead.model_validate(obj) if obj else None


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


async def list_chunks(
    session: AsyncSession,
    *,
    analysis_session_id: UUID,
    chunk_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[PaperChunkRead], int]:
    query = select(PaperChunk).where(
        PaperChunk.analysis_session_id == analysis_session_id,
    )
    count_query = select(func.count(PaperChunk.id)).where(
        PaperChunk.analysis_session_id == analysis_session_id,
    )
    if chunk_type is not None:
        query = query.where(PaperChunk.chunk_type == chunk_type)
        count_query = count_query.where(PaperChunk.chunk_type == chunk_type)

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(PaperChunk.ordinal).offset(offset).limit(limit)
    )
    items = [PaperChunkRead.model_validate(c) for c in result.scalars().all()]
    return items, total


# ---------------------------------------------------------------------------
# Graph nodes / edges
# ---------------------------------------------------------------------------


async def list_graph_nodes(
    session: AsyncSession,
    *,
    analysis_session_id: UUID,
    node_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[GraphNodeRead], int]:
    query = select(GraphNode).where(
        GraphNode.analysis_session_id == analysis_session_id,
    )
    count_query = select(func.count(GraphNode.id)).where(
        GraphNode.analysis_session_id == analysis_session_id,
    )
    if node_type is not None:
        query = query.where(GraphNode.node_type == node_type)
        count_query = count_query.where(GraphNode.node_type == node_type)

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(GraphNode.created_at).offset(offset).limit(limit)
    )
    items = [GraphNodeRead.model_validate(n) for n in result.scalars().all()]
    return items, total


async def list_graph_edges(
    session: AsyncSession,
    *,
    analysis_session_id: UUID,
    edge_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[GraphEdgeRead], int]:
    query = select(GraphEdge).where(
        GraphEdge.analysis_session_id == analysis_session_id,
    )
    count_query = select(func.count(GraphEdge.id)).where(
        GraphEdge.analysis_session_id == analysis_session_id,
    )
    if edge_type is not None:
        query = query.where(GraphEdge.edge_type == edge_type)
        count_query = count_query.where(GraphEdge.edge_type == edge_type)

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(GraphEdge.created_at).offset(offset).limit(limit)
    )
    items = [GraphEdgeRead.model_validate(e) for e in result.scalars().all()]
    return items, total


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


async def get_coverage(
    session: AsyncSession,
    analysis_session_id: UUID,
) -> CoverageDiagnosticRead | None:
    result = await session.execute(
        select(CoverageDiagnostic).where(
            CoverageDiagnostic.analysis_session_id == analysis_session_id,
        )
    )
    obj = result.scalar_one_or_none()
    return CoverageDiagnosticRead.model_validate(obj) if obj else None


# ---------------------------------------------------------------------------
# Analysis packet + review (latest-wins for paper-keyed endpoints)
# ---------------------------------------------------------------------------


async def _latest_completed_session(
    session: AsyncSession,
    paper_card_id: UUID,
) -> AnalysisSession | None:
    """Return the latest completed analysis session for a paper."""
    result = await session.execute(
        select(AnalysisSession)
        .where(
            AnalysisSession.paper_card_id == paper_card_id,
            AnalysisSession.status == "completed",
        )
        .order_by(AnalysisSession.completed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_analysis_packet(
    session: AsyncSession,
    paper_card_id: UUID,
) -> PaperAnalysisPacketRead | None:
    """Get the analysis packet from the latest completed session."""
    latest = await _latest_completed_session(session, paper_card_id)
    if latest is None:
        return None
    result = await session.execute(
        select(PaperAnalysisPacket).where(
            PaperAnalysisPacket.analysis_session_id == latest.id,
        )
    )
    obj = result.scalar_one_or_none()
    return PaperAnalysisPacketRead.model_validate(obj) if obj else None


async def get_review_artifact(
    session: AsyncSession,
    paper_card_id: UUID,
) -> PaperReviewArtifactRead | None:
    """Get the review artifact from the latest completed session."""
    latest = await _latest_completed_session(session, paper_card_id)
    if latest is None:
        return None
    result = await session.execute(
        select(PaperReviewArtifact)
        .join(PaperAnalysisPacket)
        .where(PaperAnalysisPacket.analysis_session_id == latest.id)
    )
    obj = result.scalar_one_or_none()
    return PaperReviewArtifactRead.model_validate(obj) if obj else None


async def read_report_file(
    session: AsyncSession,
    session_id: UUID,
) -> AnalysisReportResponse:
    """Read the on-disk analysis report bundle for a session."""
    import orjson

    analysis = await session.get(AnalysisSession, session_id)
    if analysis is None:
        raise AnalysisServiceError(f"analysis session {session_id} not found")

    if not analysis.report_artifact_path:
        return AnalysisReportResponse(
            session_id=session_id,
            markdown=None,
            json=None,
        )

    from pathlib import Path

    md_path = Path(analysis.report_artifact_path)
    markdown: str | None = None
    json_payload: dict | None = None

    if md_path.exists():
        markdown = md_path.read_text(encoding="utf-8")

    json_path = md_path.with_name("report.json")
    if json_path.exists():
        try:
            json_payload = orjson.loads(json_path.read_bytes())
        except orjson.JSONDecodeError:
            json_payload = None

    return AnalysisReportResponse(
        session_id=session_id,
        markdown=markdown,
        json=json_payload,
    )


# ---------------------------------------------------------------------------
# Evidence cards
# ---------------------------------------------------------------------------


async def list_evidence_cards(
    session: AsyncSession,
    *,
    charter_id: UUID | None = None,
    cycle_id: UUID | None = None,
    evidence_type: str | None = None,
    min_confidence: float | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[EvidenceCardRead], int]:
    query = select(EvidenceCard)
    count_query = select(func.count(EvidenceCard.id))

    if charter_id is not None:
        query = query.where(EvidenceCard.charter_id == charter_id)
        count_query = count_query.where(EvidenceCard.charter_id == charter_id)
    if cycle_id is not None:
        query = query.where(EvidenceCard.cycle_id == cycle_id)
        count_query = count_query.where(EvidenceCard.cycle_id == cycle_id)
    if evidence_type is not None:
        query = query.where(EvidenceCard.evidence_type == evidence_type)
        count_query = count_query.where(
            EvidenceCard.evidence_type == evidence_type,
        )
    if min_confidence is not None:
        query = query.where(EvidenceCard.confidence >= min_confidence)
        count_query = count_query.where(
            EvidenceCard.confidence >= min_confidence,
        )

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(EvidenceCard.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        EvidenceCardRead.model_validate(e)
        for e in result.scalars().all()
    ]
    return items, total


async def get_evidence_card(
    session: AsyncSession,
    evidence_id: UUID,
) -> EvidenceCardRead | None:
    obj = await session.get(EvidenceCard, evidence_id)
    return EvidenceCardRead.model_validate(obj) if obj else None


async def run_qa(
    session: AsyncSession,
    *,
    paper_card_id: UUID,
    question: str,
    max_chunks: int,
    expand_graph: bool,
) -> QAResponse:
    """Run graph-aware QA against the latest completed analysis for a paper."""
    from libs.analysis.graph_qa import answer_question

    _ = session
    sync_factory = get_sync_session_factory()
    with sync_factory() as sync_session:
        try:
            return await answer_question(
                sync_session,
                paper_card_id=paper_card_id,
                question=question,
                max_chunks=max_chunks,
                expand_graph=expand_graph,
            )
        except ValueError as exc:
            raise AnalysisServiceError(str(exc)) from exc


async def run_locate(
    session: AsyncSession,
    *,
    paper_card_id: UUID,
    entity_type: str,
    query: str,
) -> LocateResponse:
    """Locate entity mentions in the latest completed analysis for a paper."""
    from libs.analysis.graph_qa import locate_entity

    _ = session
    sync_factory = get_sync_session_factory()
    with sync_factory() as sync_session:
        matches = await locate_entity(
            sync_session,
            paper_card_id=paper_card_id,
            entity_type=entity_type,
            query=query,
        )
        return LocateResponse(matches=matches)
