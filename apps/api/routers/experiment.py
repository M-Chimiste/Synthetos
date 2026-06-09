"""Phase 3 experiment API router -- hypotheses, protocols, runs, verification."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.core.services.experiment_service import (
    ExperimentServiceError,
    compile_protocols,
    control_run,
    get_experiment_spec,
    get_failure_postmortem,
    get_hypothesis_card,
    get_hypothesis_session,
    get_run_record,
    get_verification_report,
    list_experiment_specs,
    list_hypothesis_cards,
    list_hypothesis_sessions,
    list_run_records,
    list_run_telemetry,
    list_verification_reports,
    start_hypothesis_session,
    start_run,
    update_hypothesis_card,
)
from libs.core.services.result_introspection import (
    ResultIntrospectionError,
    normalize_run_artifacts,
    resolve_run_artifact_path,
)
from libs.schemas.common import PaginatedResponse
from libs.schemas.experiment import (
    ExperimentSpecCompileRequest,
    ExperimentSpecCompileResponse,
    ExperimentSpecRead,
    FailurePostmortemRead,
    HypothesisCardRead,
    HypothesisCardUpdate,
    HypothesisSessionRead,
    HypothesisSessionStartRequest,
    HypothesisSessionStartResponse,
    RunControlRequest,
    RunRecordRead,
    RunStartRequest,
    RunStartResponse,
    RunTelemetryRead,
    VerificationReportRead,
)
from libs.schemas.results import RunArtifactRead
from libs.storage.models.experiment import RunRecord, RunTelemetry

router = APIRouter(tags=["experiment"])

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_TELEMETRY_POLL_INTERVAL = 1.0  # seconds

async def _telemetry_stream(
    db: AsyncSession,
    run_id: UUID,
    last_event_id: UUID | None,
) -> AsyncGenerator[str]:
    """Async generator that polls run_telemetry and yields SSE frames."""
    cursor = last_event_id

    while True:
        query = (
            select(RunTelemetry)
            .where(RunTelemetry.run_record_id == run_id)
            .order_by(RunTelemetry.timestamp.asc())
        )
        if cursor is not None:
            query = query.where(RunTelemetry.id > cursor)
        query = query.limit(100)

        result = await db.execute(query)
        rows = result.scalars().all()

        for row in rows:
            data = RunTelemetryRead.model_validate(row)
            payload = json.dumps(data.model_dump(mode="json"), default=str)
            yield f"id: {data.id}\ndata: {payload}\n\n"
            cursor = row.id

        # Check if run is terminal
        run = await db.get(RunRecord, run_id)
        if run is not None and run.status in _TERMINAL_STATUSES:
            yield "event: done\ndata: {}\n\n"
            return

        await asyncio.sleep(_TELEMETRY_POLL_INTERVAL)

# ---- Hypothesis sessions ---------------------------------------------------

@router.post(
    "/hypotheses/sessions",
    response_model=HypothesisSessionStartResponse,
    status_code=201,
)
async def start_hypothesis_session_endpoint(
    body: HypothesisSessionStartRequest,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> HypothesisSessionStartResponse:
    try:
        session_read, job_id = await start_hypothesis_session(
            db,
            cycle_id=body.cycle_id,
            charter_id=body.charter_id,
            budget=body.budget,
        )
    except ExperimentServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HypothesisSessionStartResponse(session=session_read, job_id=job_id)

@router.get("/hypotheses/sessions", response_model=PaginatedResponse[HypothesisSessionRead])
async def list_hypothesis_sessions_endpoint(
    charter_id: UUID | None = Query(default=None),
    cycle_id: UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[HypothesisSessionRead]:
    items, total = await list_hypothesis_sessions(
        db, charter_id=charter_id, cycle_id=cycle_id, offset=offset, limit=limit
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

@router.get("/hypotheses/sessions/{session_id}", response_model=HypothesisSessionRead)
async def get_hypothesis_session_endpoint(
    session_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> HypothesisSessionRead:
    result = await get_hypothesis_session(db, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Hypothesis session not found")
    return result

# ---- Hypothesis cards ------------------------------------------------------

@router.get("/hypotheses/cards", response_model=PaginatedResponse[HypothesisCardRead])
async def list_hypothesis_cards_endpoint(
    cycle_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[HypothesisCardRead]:
    items, total = await list_hypothesis_cards(
        db, cycle_id=cycle_id, status=status, offset=offset, limit=limit
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

@router.get("/hypotheses/cards/{card_id}", response_model=HypothesisCardRead)
async def get_hypothesis_card_endpoint(
    card_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> HypothesisCardRead:
    result = await get_hypothesis_card(db, card_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Hypothesis card not found")
    return result

@router.patch("/hypotheses/cards/{card_id}", response_model=HypothesisCardRead)
async def update_hypothesis_card_endpoint(
    card_id: UUID,
    body: HypothesisCardUpdate,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> HypothesisCardRead:
    try:
        return await update_hypothesis_card(db, card_id, body)
    except ExperimentServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

# ---- Experiment specs ------------------------------------------------------

@router.get("/protocols/specs", response_model=PaginatedResponse[ExperimentSpecRead])
async def list_experiment_specs_endpoint(
    cycle_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ExperimentSpecRead]:
    items, total = await list_experiment_specs(
        db, cycle_id=cycle_id, status=status, offset=offset, limit=limit
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

@router.get("/protocols/specs/{spec_id}", response_model=ExperimentSpecRead)
async def get_experiment_spec_endpoint(
    spec_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> ExperimentSpecRead:
    result = await get_experiment_spec(db, spec_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Experiment spec not found")
    return result

# ---- Protocol compilation ---------------------------------------------------

@router.post(
    "/protocols/compile",
    response_model=ExperimentSpecCompileResponse,
    status_code=201,
)
async def compile_protocols_endpoint(
    body: ExperimentSpecCompileRequest,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> ExperimentSpecCompileResponse:
    try:
        specs, job_id = await compile_protocols(db, body=body)
    except ExperimentServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExperimentSpecCompileResponse(specs=specs, job_id=job_id)

# ---- Run records -----------------------------------------------------------

@router.post("/runs", response_model=RunStartResponse, status_code=201)
async def start_run_endpoint(
    body: RunStartRequest,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> RunStartResponse:
    try:
        run_read, job_id = await start_run(
            db, experiment_spec_id=body.experiment_spec_id, gpu_enabled=body.gpu_enabled
        )
    except ExperimentServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RunStartResponse(run=run_read, job_id=job_id)

@router.get("/runs", response_model=PaginatedResponse[RunRecordRead])
async def list_run_records_endpoint(
    cycle_id: UUID | None = Query(default=None),
    spec_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[RunRecordRead]:
    items, total = await list_run_records(
        db,
        cycle_id=cycle_id,
        experiment_spec_id=spec_id,
        status=status,
        offset=offset,
        limit=limit,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)

@router.get("/runs/{run_id}", response_model=RunRecordRead)
async def get_run_record_endpoint(
    run_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> RunRecordRead:
    result = await get_run_record(db, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run record not found")
    return result


@router.get("/runs/{run_id}/artifacts", response_model=list[RunArtifactRead])
async def list_run_artifacts_endpoint(
    run_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> list[RunArtifactRead]:
    run = await db.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run record not found")
    return normalize_run_artifacts(run)


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
async def download_run_artifact_endpoint(
    run_id: UUID,
    artifact_id: str,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    try:
        file_path, artifact = await db.run_sync(
            lambda s: resolve_run_artifact_path(s, run_id, artifact_id)
        )
    except ResultIntrospectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(file_path, filename=artifact.name)

# ---- Run control -----------------------------------------------------------

@router.post("/runs/{run_id}/control", response_model=RunRecordRead)
async def control_run_endpoint(
    run_id: UUID,
    body: RunControlRequest,
    _: None = Depends(require_scope("cycles.write")),
    db: AsyncSession = Depends(get_db),
) -> RunRecordRead:
    try:
        return await control_run(db, run_id, body.action)
    except ExperimentServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

# ---- Run telemetry ---------------------------------------------------------

@router.get("/runs/{run_id}/telemetry", response_model=list[RunTelemetryRead])
async def list_run_telemetry_endpoint(
    run_id: UUID,
    since: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> list[RunTelemetryRead]:
    return await list_run_telemetry(db, run_id, since=since, limit=limit)

@router.get("/runs/{run_id}/telemetry/stream")
async def stream_run_telemetry(
    run_id: UUID,
    last_event_id: UUID | None = Query(default=None),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream run telemetry as Server-Sent Events.

    Polls the run_telemetry table every second for new entries.
    Closes when the run reaches a terminal status.
    """
    return StreamingResponse(
        _telemetry_stream(db, run_id, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# ---- Verification ----------------------------------------------------------

@router.get("/runs/{run_id}/verification", response_model=VerificationReportRead)
async def get_verification_report_endpoint(
    run_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> VerificationReportRead:
    result = await get_verification_report(db, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Verification report not found")
    return result

@router.get("/runs/{run_id}/postmortem", response_model=FailurePostmortemRead)
async def get_failure_postmortem_endpoint(
    run_id: UUID,
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> FailurePostmortemRead:
    result = await get_failure_postmortem(db, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Failure postmortem not found")
    return result

@router.get("/verifications", response_model=PaginatedResponse[VerificationReportRead])
async def list_verifications_endpoint(
    cycle_id: UUID | None = Query(default=None),
    verdict: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("cycles.read")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[VerificationReportRead]:
    items, total = await list_verification_reports(
        db, cycle_id=cycle_id, verdict=verdict, offset=offset, limit=limit
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)
