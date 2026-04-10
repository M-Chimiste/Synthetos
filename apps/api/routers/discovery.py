"""Phase 1 discovery API router."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.core.services.discovery_service import (
    DiscoveryServiceError,
    get_discovery_session,
    get_paper_card,
    get_profile_for_session,
    list_discovery_sessions,
    list_evaluations,
    list_paper_cards,
    read_report_file,
    start_discovery_session,
    submit_evaluation,
    triage_paper_card,
)
from libs.schemas.common import PaginatedResponse
from libs.schemas.discovery import (
    DiscoverySessionRead,
    DiscoverySessionStartResponse,
    EvaluationMetricRead,
    EvaluationSubmission,
    ProblemProfileCreate,
    ProblemProfileRead,
    TriageRequest,
)
from libs.schemas.papers import PaperCardRead

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["discovery"])


# ---- Start a discovery session on a charter ------------------------------


@router.post(
    "/charters/{charter_id}/discovery",
    response_model=DiscoverySessionStartResponse,
    status_code=201,
)
async def start_discovery_endpoint(
    charter_id: UUID,
    body: ProblemProfileCreate,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> DiscoverySessionStartResponse:
    try:
        session, profile, job_id = await start_discovery_session(
            db,
            charter_id=charter_id,
            body=body,
        )
    except DiscoveryServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DiscoverySessionStartResponse(session=session, profile=profile, job_id=job_id)


# ---- List sessions across charters or for one charter -------------------


@router.get(
    "/discovery",
    response_model=PaginatedResponse[DiscoverySessionRead],
)
async def list_discovery_sessions_endpoint(
    charter_id: UUID | None = None,
    offset: int = 0,
    limit: int = 50,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[DiscoverySessionRead]:
    items, total = await list_discovery_sessions(
        db, charter_id=charter_id, offset=offset, limit=limit
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


# ---- Single session -----------------------------------------------------


@router.get("/discovery/{session_id}", response_model=DiscoverySessionRead)
async def get_discovery_session_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> DiscoverySessionRead:
    obj = await get_discovery_session(db, session_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="discovery session not found")
    return obj


@router.get(
    "/discovery/{session_id}/profile",
    response_model=ProblemProfileRead,
)
async def get_session_profile_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> ProblemProfileRead:
    obj = await get_profile_for_session(db, session_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return obj


# ---- Paper cards --------------------------------------------------------


@router.get(
    "/discovery/{session_id}/papers",
    response_model=PaginatedResponse[PaperCardRead],
)
async def list_session_papers_endpoint(
    session_id: UUID,
    view: str | None = Query(default=None, pattern="^(stable|discovery)$"),
    triage_status: str | None = None,
    min_score: float | None = None,
    offset: int = 0,
    limit: int = 50,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[PaperCardRead]:
    items, total = await list_paper_cards(
        db,
        session_id=session_id,
        view=view,
        triage_status=triage_status,
        min_score=min_score,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get(
    "/discovery/{session_id}/papers/{paper_id}",
    response_model=PaperCardRead,
)
async def get_session_paper_endpoint(
    session_id: UUID,
    paper_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaperCardRead:
    obj = await get_paper_card(db, session_id, paper_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="paper not found")
    return obj


@router.post(
    "/discovery/{session_id}/papers/{paper_id}/triage",
    response_model=PaperCardRead,
)
async def triage_paper_endpoint(
    session_id: UUID,
    paper_id: UUID,
    body: TriageRequest,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> PaperCardRead:
    obj = await triage_paper_card(
        db,
        session_id=session_id,
        paper_id=paper_id,
        triage_status=body.triage_status,
        triage_reason=body.triage_reason,
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="paper not found")
    return obj


# ---- Report bundle ------------------------------------------------------


@router.get("/discovery/{session_id}/report")
async def get_session_report_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        _session, markdown, json_payload = await read_report_file(db, session_id)
    except DiscoveryServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if markdown is None and json_payload is None:
        raise HTTPException(
            status_code=404,
            detail="discovery report not yet generated for this session",
        )
    return {
        "session_id": str(session_id),
        "markdown": markdown,
        "json": json_payload,
    }


# ---- Evaluation hooks ---------------------------------------------------


@router.post(
    "/discovery/{session_id}/evaluation",
    response_model=list[EvaluationMetricRead],
    status_code=201,
)
async def submit_evaluation_endpoint(
    session_id: UUID,
    body: EvaluationSubmission,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> list[EvaluationMetricRead]:
    try:
        return await submit_evaluation(db, session_id=session_id, submission=body)
    except DiscoveryServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/discovery/{session_id}/evaluation",
    response_model=list[EvaluationMetricRead],
)
async def list_evaluation_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> list[EvaluationMetricRead]:
    return await list_evaluations(db, session_id)
