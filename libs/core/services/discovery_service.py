"""Async business logic for the Phase 1 discovery API.

These functions are called from :mod:`apps.api.routers.discovery`.  They
create discovery sessions, enqueue the operator chain, query results, and
record evaluation metrics.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.event_types import DiscoveryEvents
from libs.core.events import emit_event
from libs.core.types import ActorType, CycleStatus, JobStatus
from libs.discovery.evaluation import mrr, precision_at_k, recall_at_k
from libs.schemas.discovery import (
    DiscoverySessionRead,
    EvaluationMetricRead,
    EvaluationSubmission,
    ProblemProfileCreate,
    ProblemProfileRead,
)
from libs.schemas.papers import PaperCardRead
from libs.storage.models.discovery import (
    DiscoveryEvaluation,
    DiscoverySession,
    ProblemProfile,
)
from libs.storage.models.jobs import Job
from libs.storage.models.papers import PaperCard
from libs.storage.models.research import ResearchCharter, ResearchCycle


class DiscoveryServiceError(Exception):
    """Raised when a discovery service operation cannot proceed."""


async def _resolve_or_create_active_cycle(
    session: AsyncSession,
    charter_id: UUID,
) -> ResearchCycle:
    """Return the latest cycle for a charter, creating one if needed."""
    result = await session.execute(
        select(ResearchCycle)
        .where(ResearchCycle.charter_id == charter_id)
        .order_by(ResearchCycle.created_at.desc())
    )
    cycles = result.scalars().all()
    for cycle in cycles:
        # Allow reuse only if the cycle hasn't moved past discovery_screened.
        if cycle.status in (
            CycleStatus.created.value,
            CycleStatus.discovery_ready.value,
        ):
            return cycle

    cycle = ResearchCycle(
        id=uuid7(),
        charter_id=charter_id,
        status=CycleStatus.created,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(cycle)
    await session.flush()
    return cycle


async def start_discovery_session(
    session: AsyncSession,
    *,
    charter_id: UUID,
    body: ProblemProfileCreate,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> tuple[DiscoverySessionRead, ProblemProfileRead, UUID]:
    """Create a profile + session and enqueue ``discovery_intake``.

    Returns ``(session, profile, intake_job_id)``.
    """
    charter = await session.get(ResearchCharter, charter_id)
    if charter is None:
        raise DiscoveryServiceError(f"charter {charter_id} not found")

    cycle = await _resolve_or_create_active_cycle(session, charter_id)

    # Reject if a profile already exists for this cycle (one per cycle in v1).
    existing_profile = await session.execute(
        select(ProblemProfile).where(ProblemProfile.cycle_id == cycle.id)
    )
    if existing_profile.scalar_one_or_none() is not None:
        raise DiscoveryServiceError(
            f"cycle {cycle.id} already has a problem profile; "
            "Phase 1 supports only one discovery session per cycle"
        )

    profile = ProblemProfile(
        id=uuid7(),
        cycle_id=cycle.id,
        query_text=body.query_text,
        notes=body.notes,
        source_scope=body.source_scope,
        view_preference=body.view_preference,
        rerank_policy=body.rerank_policy.model_dump(),
        budget=body.budget.model_dump(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(profile)

    discovery = DiscoverySession(
        id=uuid7(),
        cycle_id=cycle.id,
        charter_id=charter_id,
        profile_id=profile.id,
        status="created",
        view=body.view_preference,
        stats={},
        step_log=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(discovery)
    await session.flush()

    # Enqueue the intake job synchronously via raw SQL-friendly construction.
    intake_job_id = uuid7()
    job = Job(
        id=intake_job_id,
        cycle_id=cycle.id,
        job_type="discovery_intake",
        status=JobStatus.pending,
        payload={"session_id": str(discovery.id)},
        priority=10,
        created_at=utcnow(),
    )
    session.add(job)

    await emit_event(
        session,
        event_type="discovery_session_created",
        charter_id=charter_id,
        cycle_id=cycle.id,
        payload={
            "session_id": str(discovery.id),
            "profile_id": str(profile.id),
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return (
        DiscoverySessionRead.model_validate(discovery),
        ProblemProfileRead.model_validate(profile),
        UUID(str(intake_job_id)),
    )


async def get_discovery_session(
    session: AsyncSession,
    session_id: UUID,
) -> DiscoverySessionRead | None:
    obj = await session.get(DiscoverySession, session_id)
    return DiscoverySessionRead.model_validate(obj) if obj else None


async def list_discovery_sessions(
    session: AsyncSession,
    *,
    charter_id: UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[DiscoverySessionRead], int]:
    query = select(DiscoverySession)
    count_query = select(DiscoverySession.id)
    if charter_id is not None:
        query = query.where(DiscoverySession.charter_id == charter_id)
        count_query = count_query.where(DiscoverySession.charter_id == charter_id)
    count = (await session.execute(count_query)).all()
    result = await session.execute(
        query.order_by(DiscoverySession.created_at.desc()).offset(offset).limit(limit)
    )
    items = [DiscoverySessionRead.model_validate(s) for s in result.scalars().all()]
    return items, len(count)


async def list_paper_cards(
    session: AsyncSession,
    *,
    session_id: UUID,
    view: str | None = None,
    triage_status: str | None = None,
    min_score: float | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[PaperCardRead], int]:
    base = select(PaperCard).where(PaperCard.session_id == session_id)
    if triage_status is not None:
        base = base.where(PaperCard.triage_status == triage_status)
    if min_score is not None:
        base = base.where(PaperCard.final_score >= min_score)

    if view is not None:
        # JSONB containment check; the column stores ``["stable", "discovery"]`` etc.
        base = base.where(PaperCard.view_membership.contains([view]))

    count_result = await session.execute(base.with_only_columns(PaperCard.id))
    total = len(count_result.all())

    result = await session.execute(
        base.order_by(PaperCard.final_score.desc().nullslast()).offset(offset).limit(limit)
    )
    items = [PaperCardRead.model_validate(c) for c in result.scalars().all()]
    return items, total


async def get_paper_card(
    session: AsyncSession,
    session_id: UUID,
    paper_id: UUID,
) -> PaperCardRead | None:
    result = await session.execute(
        select(PaperCard).where(
            PaperCard.id == paper_id,
            PaperCard.session_id == session_id,
        )
    )
    obj = result.scalar_one_or_none()
    return PaperCardRead.model_validate(obj) if obj else None


async def triage_paper_card(
    session: AsyncSession,
    *,
    session_id: UUID,
    paper_id: UUID,
    triage_status: str,
    triage_reason: str | None,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> PaperCardRead | None:
    discovery = await session.get(DiscoverySession, session_id)
    if discovery is None:
        return None

    result = await session.execute(
        select(PaperCard).where(
            PaperCard.id == paper_id,
            PaperCard.session_id == session_id,
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        return None
    obj.triage_status = triage_status
    obj.triage_reason = triage_reason
    obj.updated_at = utcnow()

    await emit_event(
        session,
        event_type=DiscoveryEvents.triage_overridden.value,
        charter_id=obj.charter_id,
        cycle_id=discovery.cycle_id,
        payload={
            "session_id": str(session_id),
            "paper_id": str(obj.id),
            "cycle_id": str(discovery.cycle_id),
            "triage_status": triage_status,
            "triage_reason": triage_reason,
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )
    await session.flush()
    return PaperCardRead.model_validate(obj)


async def get_profile_for_session(
    session: AsyncSession,
    session_id: UUID,
) -> ProblemProfileRead | None:
    discovery = await session.get(DiscoverySession, session_id)
    if discovery is None:
        return None
    profile = await session.get(ProblemProfile, discovery.profile_id)
    return ProblemProfileRead.model_validate(profile) if profile else None


async def submit_evaluation(
    session: AsyncSession,
    *,
    session_id: UUID,
    submission: EvaluationSubmission,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> list[EvaluationMetricRead]:
    discovery = await session.get(DiscoverySession, session_id)
    if discovery is None:
        raise DiscoveryServiceError(f"session {session_id} not found")

    result = await session.execute(
        select(PaperCard)
        .where(PaperCard.session_id == session_id)
        .order_by(PaperCard.final_score.desc().nullslast())
    )
    ranked = list(result.scalars().all())
    relevant = set(submission.relevant_ids)

    metric_rows: list[DiscoveryEvaluation] = []

    def _add(metric: str, k: int | None, value: float) -> None:
        row = DiscoveryEvaluation(
            id=uuid7(),
            session_id=session_id,
            metric=metric,
            k=k,
            value=value,
            source="user_supplied",
            notes=submission.notes,
            created_at=utcnow(),
        )
        session.add(row)
        metric_rows.append(row)

    for k in submission.k_values:
        _add("recall_at_k", k, recall_at_k(ranked, relevant, k))
        _add("precision_at_k", k, precision_at_k(ranked, relevant, k))
    _add("mrr", None, mrr(ranked, relevant))

    await emit_event(
        session,
        event_type=DiscoveryEvents.evaluation_recorded.value,
        charter_id=discovery.charter_id,
        cycle_id=discovery.cycle_id,
        payload={
            "session_id": str(session_id),
            "metrics": [
                {"metric": m.metric, "k": m.k, "value": float(m.value)} for m in metric_rows
            ],
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return [EvaluationMetricRead.model_validate(m) for m in metric_rows]


async def list_evaluations(
    session: AsyncSession,
    session_id: UUID,
) -> list[EvaluationMetricRead]:
    result = await session.execute(
        select(DiscoveryEvaluation)
        .where(DiscoveryEvaluation.session_id == session_id)
        .order_by(DiscoveryEvaluation.created_at.desc())
    )
    return [EvaluationMetricRead.model_validate(m) for m in result.scalars().all()]


async def read_report_file(
    session: AsyncSession,
    session_id: UUID,
) -> tuple[DiscoverySession, str | None, dict | None]:
    """Read the on-disk report bundle written by ``discovery_finalize``.

    Returns ``(session, markdown_text, json_payload)``.  Either may be ``None``
    if the file is missing.
    """
    import orjson

    discovery = await session.get(DiscoverySession, session_id)
    if discovery is None:
        raise DiscoveryServiceError(f"session {session_id} not found")

    if not discovery.report_artifact_path:
        return discovery, None, None

    from pathlib import Path

    md_path = Path(discovery.report_artifact_path)
    md_text: str | None = None
    json_payload: dict | None = None

    if md_path.exists():
        md_text = md_path.read_text(encoding="utf-8")

    json_path = md_path.with_name("report.json")
    if json_path.exists():
        try:
            json_payload = orjson.loads(json_path.read_bytes())
        except orjson.JSONDecodeError:
            json_payload = None

    # ``datetime`` import retained for type stability if extended later.
    _ = datetime
    return discovery, md_text, json_payload
