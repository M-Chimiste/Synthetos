"""Phase 2 analysis API router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.core.services.analysis_service import (
    AnalysisServiceError,
    get_analysis_packet,
    get_analysis_session,
    get_coverage,
    get_evidence_card,
    get_ingested_document,
    get_review_artifact,
    list_analysis_sessions,
    list_chunks,
    list_evidence_cards,
    list_graph_edges,
    list_graph_nodes,
    read_report_file,
    run_locate,
    run_qa,
    start_analysis,
)
from libs.schemas.analysis import (
    AnalysisReportResponse,
    AnalysisSessionRead,
    AnalysisSessionStartRequest,
    AnalysisSessionStartResponse,
    CoverageDiagnosticRead,
    EvidenceCardRead,
    GraphEdgeRead,
    GraphNodeRead,
    IngestedDocumentRead,
    LocateRequest,
    LocateResponse,
    PaperAnalysisPacketRead,
    PaperChunkRead,
    PaperReviewArtifactRead,
    QARequest,
    QAResponse,
)
from libs.schemas.common import PaginatedResponse

router = APIRouter(tags=["analysis"])

# ---- Start analysis -------------------------------------------------------

@router.post(
    "/papers/{paper_card_id}/analyze",
    response_model=AnalysisSessionStartResponse,
    status_code=201,
)
async def start_analysis_endpoint(
    paper_card_id: UUID,
    body: AnalysisSessionStartRequest | None = None,
    charter_id: UUID = Query(...),
    cycle_id: UUID = Query(...),
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> AnalysisSessionStartResponse:
    payload = body or AnalysisSessionStartRequest()
    try:
        session_read, job_id = await start_analysis(
            db,
            paper_card_id=paper_card_id,
            charter_id=charter_id,
            cycle_id=cycle_id,
            budget=payload.budget,
        )
    except AnalysisServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return AnalysisSessionStartResponse(session=session_read, job_id=job_id)

# ---- Analysis sessions ----------------------------------------------------

@router.get("/analysis", response_model=PaginatedResponse[AnalysisSessionRead])
async def list_sessions_endpoint(
    charter_id: UUID | None = None,
    cycle_id: UUID | None = None,
    status: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AnalysisSessionRead]:
    items, total = await list_analysis_sessions(
        db,
        charter_id=charter_id,
        cycle_id=cycle_id,
        status=status,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

@router.get(
    "/analysis/{session_id}",
    response_model=AnalysisSessionRead,
)
async def get_session_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> AnalysisSessionRead:
    result = await get_analysis_session(db, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Analysis session not found")
    return result

# ---- Ingested document -----------------------------------------------------

@router.get(
    "/analysis/{session_id}/document",
    response_model=IngestedDocumentRead,
)
async def get_document_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> IngestedDocumentRead:
    result = await get_ingested_document(db, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Ingested document not found")
    return result

# ---- Chunks ----------------------------------------------------------------

@router.get(
    "/analysis/{session_id}/chunks",
    response_model=PaginatedResponse[PaperChunkRead],
)
async def list_chunks_endpoint(
    session_id: UUID,
    chunk_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[PaperChunkRead]:
    items, total = await list_chunks(
        db,
        analysis_session_id=session_id,
        chunk_type=chunk_type,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

# ---- Graph nodes / edges ---------------------------------------------------

@router.get(
    "/analysis/{session_id}/graph/nodes",
    response_model=PaginatedResponse[GraphNodeRead],
)
async def list_nodes_endpoint(
    session_id: UUID,
    node_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[GraphNodeRead]:
    items, total = await list_graph_nodes(
        db,
        analysis_session_id=session_id,
        node_type=node_type,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

@router.get(
    "/analysis/{session_id}/graph/edges",
    response_model=PaginatedResponse[GraphEdgeRead],
)
async def list_edges_endpoint(
    session_id: UUID,
    edge_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[GraphEdgeRead]:
    items, total = await list_graph_edges(
        db,
        analysis_session_id=session_id,
        edge_type=edge_type,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

# ---- Coverage --------------------------------------------------------------

@router.get(
    "/analysis/{session_id}/coverage",
    response_model=CoverageDiagnosticRead,
)
async def get_coverage_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> CoverageDiagnosticRead:
    result = await get_coverage(db, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Coverage diagnostic not found")
    return result

# ---- Paper-keyed endpoints (latest-wins) -----------------------------------

@router.get(
    "/papers/{paper_card_id}/analysis-packet",
    response_model=PaperAnalysisPacketRead,
)
async def get_packet_endpoint(
    paper_card_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaperAnalysisPacketRead:
    result = await get_analysis_packet(db, paper_card_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Analysis packet not found")
    return result

@router.get(
    "/papers/{paper_card_id}/review",
    response_model=PaperReviewArtifactRead,
)
async def get_review_endpoint(
    paper_card_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaperReviewArtifactRead:
    result = await get_review_artifact(db, paper_card_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Review artifact not found")
    return result

@router.post("/papers/{paper_card_id}/qa", response_model=QAResponse)
async def qa_endpoint(
    paper_card_id: UUID,
    body: QARequest,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> QAResponse:
    try:
        return await run_qa(
            db,
            paper_card_id=paper_card_id,
            question=body.question,
            max_chunks=body.max_chunks,
            expand_graph=body.expand_graph,
        )
    except AnalysisServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/papers/{paper_card_id}/locate", response_model=LocateResponse)
async def locate_endpoint(
    paper_card_id: UUID,
    body: LocateRequest,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> LocateResponse:
    return await run_locate(
        db,
        paper_card_id=paper_card_id,
        entity_type=body.entity_type,
        query=body.query,
    )

@router.get("/analysis/{session_id}/report", response_model=AnalysisReportResponse)
async def get_report_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> AnalysisReportResponse:
    try:
        report = await read_report_file(db, session_id)
    except AnalysisServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if report.markdown is None and report.json_payload is None:
        raise HTTPException(
            status_code=404,
            detail="analysis report not yet generated for this session",
        )
    return report

# ---- Evidence cards --------------------------------------------------------

@router.get("/evidence", response_model=PaginatedResponse[EvidenceCardRead])
async def list_evidence_endpoint(
    charter_id: UUID | None = None,
    cycle_id: UUID | None = None,
    evidence_type: str | None = None,
    min_confidence: float | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EvidenceCardRead]:
    items, total = await list_evidence_cards(
        db,
        charter_id=charter_id,
        cycle_id=cycle_id,
        evidence_type=evidence_type,
        min_confidence=min_confidence,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

@router.get("/evidence/{evidence_id}", response_model=EvidenceCardRead)
async def get_evidence_endpoint(
    evidence_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> EvidenceCardRead:
    result = await get_evidence_card(db, evidence_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evidence card not found")
    return result
