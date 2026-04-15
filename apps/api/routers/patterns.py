"""Phase 6 canonical patterns API."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from apps.api.auth import require_scope
from apps.api.deps import get_db
from libs.core.clock import utcnow
from libs.core.event_types import PatternEvents
from libs.core.types import JobStatus
from libs.schemas.patterns import (
    ApproveRequest,
    ConsolidateRequest,
    DecayRequest,
    JobAcceptedResponse,
    ObservationList,
    PatternApprovalRead,
    PatternDetail,
    PatternList,
    PatternMatchRead,
    PatternObservationRead,
    PatternSummary,
    RejectRequest,
    RetrievePreviewRequest,
    TrustTierUpdateRequest,
)
from libs.storage.models.jobs import Job
from libs.storage.models.patterns import (
    CanonicalPattern,
    PatternApproval,
    PatternObservation,
)

router = APIRouter(prefix="/patterns", tags=["patterns"])


VALID_TRUST_TIERS = {"auto", "curated", "deprecated"}


def _to_summary(p: CanonicalPattern) -> PatternSummary:
    return PatternSummary(
        id=p.id,
        pattern_type=p.pattern_type,
        title=p.title,
        summary=p.summary,
        trust_tier=p.trust_tier,
        evidence_count=p.evidence_count,
        confidence=p.confidence,
        staleness_score=p.staleness_score,
        source_charter_ids=list(p.source_charter_ids or []),
        last_reinforced_at=p.last_reinforced_at,
    )


def _to_observation_read(o: PatternObservation) -> PatternObservationRead:
    return PatternObservationRead(
        id=o.id,
        pattern_id=o.pattern_id,
        charter_id=o.charter_id,
        cycle_id=o.cycle_id,
        source_artifact_type=o.source_artifact_type,
        source_artifact_id=o.source_artifact_id,
        contribution=o.contribution,
        observed_at=o.observed_at,
    )


def _to_approval_read(a: PatternApproval) -> PatternApprovalRead:
    return PatternApprovalRead(
        id=a.id,
        pattern_id=a.pattern_id,
        charter_id=a.charter_id,
        decision=a.decision,
        actor_type=a.actor_type,
        actor_id=a.actor_id,
        rationale=a.rationale,
        expires_at=a.expires_at,
        created_at=a.created_at,
    )


async def _emit(
    db: AsyncSession,
    *,
    event_type: str,
    charter_id: UUID | None = None,
    cycle_id: UUID | None = None,
    payload: dict | None = None,
) -> None:
    from libs.core.events import emit_event

    await emit_event(
        db,
        event_type=event_type,
        charter_id=charter_id,
        cycle_id=cycle_id,
        payload=payload,
    )


@router.get("", response_model=PatternList)
async def list_patterns(
    pattern_type: str | None = None,
    trust_tier: str | None = None,
    min_confidence: float = 0.0,
    charter_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_scope("patterns.read")),
    db: AsyncSession = Depends(get_db),
) -> PatternList:
    stmt = select(CanonicalPattern)
    count_stmt = select(func.count()).select_from(CanonicalPattern)
    if pattern_type:
        stmt = stmt.where(CanonicalPattern.pattern_type == pattern_type)
        count_stmt = count_stmt.where(CanonicalPattern.pattern_type == pattern_type)
    if trust_tier:
        stmt = stmt.where(CanonicalPattern.trust_tier == trust_tier)
        count_stmt = count_stmt.where(CanonicalPattern.trust_tier == trust_tier)
    if min_confidence > 0:
        stmt = stmt.where(CanonicalPattern.confidence >= min_confidence)
        count_stmt = count_stmt.where(CanonicalPattern.confidence >= min_confidence)
    if charter_id is not None:
        stmt = stmt.where(CanonicalPattern.source_charter_ids.any(charter_id))  # type: ignore[attr-defined]
        count_stmt = count_stmt.where(
            CanonicalPattern.source_charter_ids.any(charter_id)  # type: ignore[attr-defined]
        )

    stmt = (
        stmt.order_by(desc(CanonicalPattern.last_reinforced_at))
        .offset(offset)
        .limit(limit)
    )
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(stmt)).scalars().all()
    return PatternList(
        items=[_to_summary(p) for p in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{pattern_id}", response_model=PatternDetail)
async def get_pattern(
    pattern_id: UUID,
    _: None = Depends(require_scope("patterns.read")),
    db: AsyncSession = Depends(get_db),
) -> PatternDetail:
    pattern = await db.get(CanonicalPattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="pattern not found")
    obs_rows = (
        await db.execute(
            select(PatternObservation)
            .where(PatternObservation.pattern_id == pattern_id)
            .order_by(desc(PatternObservation.observed_at))
            .limit(20)
        )
    ).scalars().all()
    summary = _to_summary(pattern)
    return PatternDetail(
        **summary.model_dump(),
        structured_body=pattern.structured_body or {},
        consolidation_version=pattern.consolidation_version,
        first_observed_at=pattern.first_observed_at,
        last_observed_at=pattern.last_observed_at,
        created_at=pattern.created_at,
        updated_at=pattern.updated_at,
        recent_observations=[_to_observation_read(o) for o in obs_rows],
    )


@router.get("/{pattern_id}/observations", response_model=ObservationList)
async def list_observations(
    pattern_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    _: None = Depends(require_scope("patterns.read")),
    db: AsyncSession = Depends(get_db),
) -> ObservationList:
    total = (
        await db.execute(
            select(func.count())
            .select_from(PatternObservation)
            .where(PatternObservation.pattern_id == pattern_id)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(PatternObservation)
            .where(PatternObservation.pattern_id == pattern_id)
            .order_by(desc(PatternObservation.observed_at))
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return ObservationList(
        items=[_to_observation_read(o) for o in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


async def _enqueue_job(
    db: AsyncSession,
    *,
    job_type: str,
    payload: dict,
    cycle_id: UUID | None = None,
    priority: int = 0,
) -> Job:
    job = Job(
        id=uuid7(),
        cycle_id=cycle_id,
        job_type=job_type,
        status=JobStatus.pending,
        payload=payload,
        priority=priority,
        created_at=utcnow(),
    )
    db.add(job)
    await db.flush()
    return job


@router.post("/consolidate", response_model=JobAcceptedResponse, status_code=202)
async def consolidate_patterns(
    body: ConsolidateRequest,
    _: None = Depends(require_scope("patterns.write")),
    db: AsyncSession = Depends(get_db),
) -> JobAcceptedResponse:
    try:
        types = body.validate_types()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = {}
    if body.charter_id is not None:
        payload["charter_id"] = str(body.charter_id)
    if types:
        payload["pattern_types"] = types
    job = await _enqueue_job(db, job_type="consolidate_patterns", payload=payload)
    return JobAcceptedResponse(job_id=job.id)


@router.post("/decay", response_model=JobAcceptedResponse, status_code=202)
async def decay_patterns(
    body: DecayRequest,
    _: None = Depends(require_scope("patterns.write")),
    db: AsyncSession = Depends(get_db),
) -> JobAcceptedResponse:
    payload: dict = {"force": bool(body.force)}
    if body.max_staleness_days is not None:
        payload["max_staleness_days"] = int(body.max_staleness_days)
    job = await _enqueue_job(db, job_type="decay_patterns", payload=payload)
    return JobAcceptedResponse(job_id=job.id)


@router.post("/{pattern_id}/approve", response_model=PatternApprovalRead)
async def approve_pattern(
    pattern_id: UUID,
    body: ApproveRequest,
    _: None = Depends(require_scope("patterns.write")),
    db: AsyncSession = Depends(get_db),
) -> PatternApprovalRead:
    pattern = await db.get(CanonicalPattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="pattern not found")
    approval = PatternApproval(
        id=uuid7(),
        pattern_id=pattern_id,
        charter_id=body.charter_id,
        decision="approve",
        actor_type="user",
        rationale=body.rationale,
        expires_at=body.expires_at,
    )
    db.add(approval)
    await db.flush()
    await _emit(
        db,
        event_type=PatternEvents.approved.value,
        charter_id=body.charter_id,
        payload={"pattern_id": str(pattern_id), "rationale": body.rationale},
    )
    return _to_approval_read(approval)


@router.post("/{pattern_id}/reject", response_model=PatternApprovalRead)
async def reject_pattern(
    pattern_id: UUID,
    body: RejectRequest,
    _: None = Depends(require_scope("patterns.write")),
    db: AsyncSession = Depends(get_db),
) -> PatternApprovalRead:
    pattern = await db.get(CanonicalPattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="pattern not found")
    approval = PatternApproval(
        id=uuid7(),
        pattern_id=pattern_id,
        charter_id=body.charter_id,
        decision="reject",
        actor_type="user",
        rationale=body.rationale,
    )
    db.add(approval)
    await db.flush()
    await _emit(
        db,
        event_type=PatternEvents.rejected.value,
        charter_id=body.charter_id,
        payload={"pattern_id": str(pattern_id), "rationale": body.rationale},
    )
    return _to_approval_read(approval)


@router.patch("/{pattern_id}/trust-tier", response_model=PatternDetail)
async def update_trust_tier(
    pattern_id: UUID,
    body: TrustTierUpdateRequest,
    _: None = Depends(require_scope("patterns.write")),
    db: AsyncSession = Depends(get_db),
) -> PatternDetail:
    if body.trust_tier not in VALID_TRUST_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"trust_tier must be one of {sorted(VALID_TRUST_TIERS)}",
        )
    pattern = await db.get(CanonicalPattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="pattern not found")
    previous = pattern.trust_tier
    pattern.trust_tier = body.trust_tier
    pattern.updated_at = utcnow()
    await _emit(
        db,
        event_type=PatternEvents.trust_tier_changed.value,
        payload={
            "pattern_id": str(pattern_id),
            "previous_tier": previous,
            "new_tier": body.trust_tier,
            "rationale": body.rationale,
        },
    )
    obs_rows = (
        await db.execute(
            select(PatternObservation)
            .where(PatternObservation.pattern_id == pattern_id)
            .order_by(desc(PatternObservation.observed_at))
            .limit(20)
        )
    ).scalars().all()
    summary = _to_summary(pattern)
    return PatternDetail(
        **summary.model_dump(),
        structured_body=pattern.structured_body or {},
        consolidation_version=pattern.consolidation_version,
        first_observed_at=pattern.first_observed_at,
        last_observed_at=pattern.last_observed_at,
        created_at=pattern.created_at,
        updated_at=pattern.updated_at,
        recent_observations=[_to_observation_read(o) for o in obs_rows],
    )


async def _retrieve_preview_rows(
    db: AsyncSession,
    *,
    body: RetrievePreviewRequest,
    pattern_types: list[str] | None,
) -> list[PatternMatchRead]:
    # Retrieval helpers live on sync sessions; run via run_sync to avoid an
    # async duplicate path for a debug endpoint.
    from libs.patterns.retrieval import find_relevant_patterns

    def _run(sync_session) -> list[PatternMatchRead]:
        matches = find_relevant_patterns(
            sync_session,
            charter_id=body.charter_id,
            current_cycle_id=body.current_cycle_id,
            problem_profile_embedding=body.problem_profile_embedding,
            pattern_types=pattern_types,
            min_confidence=body.min_confidence,
            max_staleness_days=body.max_staleness_days,
            cross_charter_only=body.cross_charter_only,
            limit=body.limit,
        )
        return [
            PatternMatchRead(
                pattern=_to_summary(m.pattern),
                similarity=m.similarity,
                effective_confidence=m.effective_confidence,
                cross_charter=m.cross_charter,
                source_charter_ids=m.source_charter_ids,
            )
            for m in matches
        ]

    return await db.run_sync(_run)


@router.post("/{pattern_id}/retrieve-preview", response_model=list[PatternMatchRead])
async def retrieve_preview_for_pattern(
    pattern_id: UUID,
    body: RetrievePreviewRequest,
    _: None = Depends(require_scope("patterns.read")),
    db: AsyncSession = Depends(get_db),
) -> list[PatternMatchRead]:
    pattern = await db.get(CanonicalPattern, pattern_id)
    if pattern is None:
        raise HTTPException(status_code=404, detail="pattern not found")
    pattern_types = body.pattern_types or [pattern.pattern_type]
    return await _retrieve_preview_rows(
        db,
        body=body,
        pattern_types=pattern_types,
    )


@router.post("/retrieve-preview", response_model=list[PatternMatchRead])
async def retrieve_preview(
    body: RetrievePreviewRequest,
    _: None = Depends(require_scope("patterns.read")),
    db: AsyncSession = Depends(get_db),
) -> list[PatternMatchRead]:
    return await _retrieve_preview_rows(
        db,
        body=body,
        pattern_types=body.pattern_types,
    )
