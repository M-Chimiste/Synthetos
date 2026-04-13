"""Async business logic for the Phase 3 experiment API.

These functions are called from :mod:`apps.api.routers.experiment`.  They
manage hypothesis sessions, protocol compilation, execution runs, and
verification queries.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from libs.adapters.container.docker_runner import DockerRunner
from libs.adapters.git.worktree import cleanup_worktree
from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.event_types import ExecutionEvents, IdeationEvents, ProtocolEvents
from libs.core.events import emit_event
from libs.core.types import ActorType, CycleStatus, JobStatus
from libs.schemas.experiment import (
    ExperimentSpecCompileRequest,
    ExperimentSpecRead,
    FailurePostmortemRead,
    HypothesisBudget,
    HypothesisCardRead,
    HypothesisCardUpdate,
    HypothesisSessionRead,
    RunRecordRead,
    RunTelemetryRead,
    VerificationReportRead,
)
from libs.storage.models.experiment import (
    ExperimentSpec,
    FailurePostmortem,
    HypothesisCard,
    HypothesisSession,
    RunRecord,
    RunTelemetry,
    VerificationReport,
)
from libs.storage.models.jobs import Job
from libs.storage.models.research import ResearchCycle


class ExperimentServiceError(Exception):
    """Raised when an experiment service operation cannot proceed."""


# ---------------------------------------------------------------------------
# Hypothesis session
# ---------------------------------------------------------------------------


async def start_hypothesis_session(
    session: AsyncSession,
    *,
    cycle_id: UUID,
    charter_id: UUID,
    budget: HypothesisBudget | None = None,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> tuple[HypothesisSessionRead, UUID]:
    """Create a hypothesis session and enqueue ``hypothesis_generate``.

    Returns ``(session_read, generate_job_id)``.
    """
    cycle = await session.get(ResearchCycle, cycle_id)
    if cycle is None:
        raise ExperimentServiceError(f"cycle {cycle_id} not found")
    if cycle.status != CycleStatus.evidence_ready.value:
        raise ExperimentServiceError(
            f"cycle {cycle_id} status is {cycle.status!r}; expected 'evidence_ready'"
        )

    hs = HypothesisSession(
        id=uuid7(),
        cycle_id=cycle_id,
        charter_id=charter_id,
        status="created",
        budget=(budget or HypothesisBudget()).model_dump(),
        stats={},
        step_log=[],
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(hs)
    await session.flush()

    job_id = uuid7()
    job = Job(
        id=job_id,
        cycle_id=cycle_id,
        job_type="hypothesis_generate",
        status=JobStatus.pending,
        payload={"hypothesis_session_id": str(hs.id)},
        priority=10,
        created_at=utcnow(),
    )
    session.add(job)

    await emit_event(
        session,
        event_type=IdeationEvents.session_started.value,
        charter_id=charter_id,
        cycle_id=cycle_id,
        payload={"hypothesis_session_id": str(hs.id)},
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return (
        HypothesisSessionRead.model_validate(hs),
        UUID(str(job_id)),
    )


async def get_hypothesis_session(
    session: AsyncSession,
    session_id: UUID,
) -> HypothesisSessionRead | None:
    obj = await session.get(HypothesisSession, session_id)
    return HypothesisSessionRead.model_validate(obj) if obj else None


async def list_hypothesis_sessions(
    session: AsyncSession,
    *,
    charter_id: UUID | None = None,
    cycle_id: UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[HypothesisSessionRead], int]:
    query = select(HypothesisSession)
    count_query = select(func.count(HypothesisSession.id))

    if charter_id is not None:
        query = query.where(HypothesisSession.charter_id == charter_id)
        count_query = count_query.where(HypothesisSession.charter_id == charter_id)
    if cycle_id is not None:
        query = query.where(HypothesisSession.cycle_id == cycle_id)
        count_query = count_query.where(HypothesisSession.cycle_id == cycle_id)

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(HypothesisSession.created_at.desc()).offset(offset).limit(limit)
    )
    items = [HypothesisSessionRead.model_validate(s) for s in result.scalars().all()]
    return items, total


# ---------------------------------------------------------------------------
# Hypothesis cards
# ---------------------------------------------------------------------------


async def list_hypothesis_cards(
    session: AsyncSession,
    *,
    cycle_id: UUID | None = None,
    hypothesis_session_id: UUID | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[HypothesisCardRead], int]:
    query = select(HypothesisCard)
    count_query = select(func.count(HypothesisCard.id))

    if cycle_id is not None:
        query = query.where(HypothesisCard.cycle_id == cycle_id)
        count_query = count_query.where(HypothesisCard.cycle_id == cycle_id)
    if hypothesis_session_id is not None:
        query = query.where(HypothesisCard.hypothesis_session_id == hypothesis_session_id)
        count_query = count_query.where(
            HypothesisCard.hypothesis_session_id == hypothesis_session_id
        )
    if status is not None:
        query = query.where(HypothesisCard.status == status)
        count_query = count_query.where(HypothesisCard.status == status)

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(HypothesisCard.rank.asc().nulls_last(), HypothesisCard.created_at)
        .offset(offset)
        .limit(limit)
    )
    items = [HypothesisCardRead.model_validate(c) for c in result.scalars().all()]
    return items, total


async def get_hypothesis_card(
    session: AsyncSession,
    card_id: UUID,
) -> HypothesisCardRead | None:
    obj = await session.get(HypothesisCard, card_id)
    return HypothesisCardRead.model_validate(obj) if obj else None


async def update_hypothesis_card(
    session: AsyncSession,
    card_id: UUID,
    body: HypothesisCardUpdate,
    *,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> HypothesisCardRead:
    """Update a hypothesis card (select, reject, or defer)."""
    card = await session.get(HypothesisCard, card_id)
    if card is None:
        raise ExperimentServiceError(f"hypothesis card {card_id} not found")

    if body.status is not None:
        card.status = body.status
    if body.rejection_reason is not None:
        card.rejection_reason = body.rejection_reason
    card.updated_at = utcnow()

    await session.flush()
    return HypothesisCardRead.model_validate(card)


# ---------------------------------------------------------------------------
# Experiment specs
# ---------------------------------------------------------------------------


async def list_experiment_specs(
    session: AsyncSession,
    *,
    cycle_id: UUID | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[ExperimentSpecRead], int]:
    query = select(ExperimentSpec)
    count_query = select(func.count(ExperimentSpec.id))

    if cycle_id is not None:
        query = query.where(ExperimentSpec.cycle_id == cycle_id)
        count_query = count_query.where(ExperimentSpec.cycle_id == cycle_id)
    if status is not None:
        query = query.where(ExperimentSpec.status == status)
        count_query = count_query.where(ExperimentSpec.status == status)

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(ExperimentSpec.created_at.desc()).offset(offset).limit(limit)
    )
    items = [ExperimentSpecRead.model_validate(s) for s in result.scalars().all()]
    return items, total


async def get_experiment_spec(
    session: AsyncSession,
    spec_id: UUID,
) -> ExperimentSpecRead | None:
    obj = await session.get(ExperimentSpec, spec_id)
    return ExperimentSpecRead.model_validate(obj) if obj else None


# ---------------------------------------------------------------------------
# Run records
# ---------------------------------------------------------------------------


async def list_run_records(
    session: AsyncSession,
    *,
    cycle_id: UUID | None = None,
    experiment_spec_id: UUID | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[RunRecordRead], int]:
    query = select(RunRecord)
    count_query = select(func.count(RunRecord.id))

    if cycle_id is not None:
        query = query.where(RunRecord.cycle_id == cycle_id)
        count_query = count_query.where(RunRecord.cycle_id == cycle_id)
    if experiment_spec_id is not None:
        query = query.where(RunRecord.experiment_spec_id == experiment_spec_id)
        count_query = count_query.where(RunRecord.experiment_spec_id == experiment_spec_id)
    if status is not None:
        query = query.where(RunRecord.status == status)
        count_query = count_query.where(RunRecord.status == status)

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(RunRecord.created_at.desc()).offset(offset).limit(limit)
    )
    items = [RunRecordRead.model_validate(r) for r in result.scalars().all()]
    return items, total


async def get_run_record(
    session: AsyncSession,
    run_id: UUID,
) -> RunRecordRead | None:
    obj = await session.get(RunRecord, run_id)
    return RunRecordRead.model_validate(obj) if obj else None


# ---------------------------------------------------------------------------
# Protocol compilation
# ---------------------------------------------------------------------------


async def compile_protocols(
    session: AsyncSession,
    *,
    body: ExperimentSpecCompileRequest,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> tuple[list[ExperimentSpecRead], UUID]:
    """Enqueue protocol compilation for selected hypotheses.

    Returns ``([], compile_job_id)`` — specs are created by the operator.
    """
    cycle = await session.get(ResearchCycle, body.cycle_id)
    if cycle is None:
        raise ExperimentServiceError(f"cycle {body.cycle_id} not found")
    if cycle.status != CycleStatus.portfolio_ready.value:
        raise ExperimentServiceError(
            f"cycle {body.cycle_id} status is {cycle.status!r}; expected 'portfolio_ready'"
        )

    # Find the hypothesis session for this cycle
    hs_result = await session.execute(
        select(HypothesisSession)
        .where(HypothesisSession.cycle_id == body.cycle_id)
        .where(HypothesisSession.status == "completed")
        .order_by(HypothesisSession.completed_at.desc())
        .limit(1)
    )
    hs = hs_result.scalar_one_or_none()
    if hs is None:
        raise ExperimentServiceError("no completed hypothesis session found for cycle")

    payload: dict = {"hypothesis_session_id": str(hs.id)}
    if body.hypothesis_card_ids:
        payload["hypothesis_card_ids"] = [str(cid) for cid in body.hypothesis_card_ids]
    if body.hardware_profile:
        payload["hardware_profile"] = body.hardware_profile
    if body.base_image:
        payload["base_image"] = body.base_image

    job_id = uuid7()
    job = Job(
        id=job_id,
        cycle_id=body.cycle_id,
        job_type="protocol_compile",
        status=JobStatus.pending,
        payload=payload,
        priority=10,
        created_at=utcnow(),
    )
    session.add(job)

    await emit_event(
        session,
        event_type=ProtocolEvents.compilation_started.value,
        charter_id=body.charter_id,
        cycle_id=body.cycle_id,
        payload={"job_id": str(job_id)},
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return [], UUID(str(job_id))


# ---------------------------------------------------------------------------
# Start run
# ---------------------------------------------------------------------------


async def start_run(
    session: AsyncSession,
    *,
    experiment_spec_id: UUID,
    gpu_enabled: bool = False,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> tuple[RunRecordRead, UUID]:
    """Create a RunRecord and enqueue ``execution_setup``.

    Returns ``(run_read, setup_job_id)``.
    """
    spec = await session.get(ExperimentSpec, experiment_spec_id)
    if spec is None:
        raise ExperimentServiceError(f"experiment spec {experiment_spec_id} not found")
    if spec.status != "validated":
        raise ExperimentServiceError(
            f"spec {experiment_spec_id} status is {spec.status!r}; expected 'validated'"
        )

    cycle = await session.get(ResearchCycle, spec.cycle_id)
    if cycle is None:
        raise ExperimentServiceError(f"cycle {spec.cycle_id} not found")

    # Transition cycle to running if in protocol_ready
    if cycle.status == CycleStatus.protocol_ready.value:
        cycle.status = CycleStatus.running
        cycle.updated_at = utcnow()

    # Determine run number
    existing_count_result = await session.execute(
        select(func.count(RunRecord.id)).where(
            RunRecord.experiment_spec_id == experiment_spec_id
        )
    )
    run_number = (existing_count_result.scalar() or 0) + 1

    run = RunRecord(
        id=uuid7(),
        experiment_spec_id=experiment_spec_id,
        charter_id=spec.charter_id,
        cycle_id=spec.cycle_id,
        run_number=run_number,
        status="pending",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(run)

    spec.status = "executing"
    spec.updated_at = utcnow()
    await session.flush()

    job_id = uuid7()
    job = Job(
        id=job_id,
        cycle_id=spec.cycle_id,
        job_type="execution_setup",
        status=JobStatus.pending,
        payload={"run_record_id": str(run.id)},
        priority=10,
        created_at=utcnow(),
    )
    session.add(job)

    await emit_event(
        session,
        event_type=ExecutionEvents.workspace_created.value,
        charter_id=spec.charter_id,
        cycle_id=spec.cycle_id,
        payload={
            "run_record_id": str(run.id),
            "experiment_spec_id": str(experiment_spec_id),
            "gpu_enabled": gpu_enabled,
        },
        actor_type=actor_type,
        actor_id=actor_id,
    )

    await session.flush()
    return (
        RunRecordRead.model_validate(run),
        UUID(str(job_id)),
    )


# ---------------------------------------------------------------------------
# Run control (pause/resume/cancel/retry)
# ---------------------------------------------------------------------------

# Canonical action rules per section 6b of the plan
_ALLOWED_ACTIONS: dict[str, list[str]] = {
    "pending": ["cancel"],
    "workspace_setup": ["cancel"],
    "building": ["cancel"],
    "running": ["pause", "cancel"],
    "paused": ["resume", "cancel"],
    "capturing": [],
    "completed": [],
    "failed": ["retry"],
    "cancelled": ["retry"],
}


async def control_run(
    session: AsyncSession,
    run_id: UUID,
    action: str,
    *,
    actor_type: ActorType = ActorType.user,
    actor_id: str | None = None,
) -> RunRecordRead:
    """Execute a run control action (pause/resume/cancel/retry).

    Raises ExperimentServiceError on illegal transitions (409).
    """
    run = await session.get(RunRecord, run_id)
    if run is None:
        raise ExperimentServiceError(f"run record {run_id} not found")

    allowed = _ALLOWED_ACTIONS.get(run.status, [])
    if action not in allowed:
        raise ExperimentServiceError(
            f"action '{action}' not allowed for run in status '{run.status}'; "
            f"allowed: {allowed or 'none'}"
        )

    if action == "cancel":
        run.status = "cancelled"
        run.completed_at = utcnow()
        run.updated_at = utcnow()
        # Cancel associated pending/running jobs for this run
        from sqlalchemy import update as sa_update

        cancellable = [
            JobStatus.pending.value,
            JobStatus.claimed.value,
            JobStatus.running.value,
            JobStatus.paused.value,
        ]
        await session.execute(
            sa_update(Job)
            .where(
                Job.status.in_(cancellable),
                Job.payload["run_record_id"].astext == str(run_id),
            )
            .values(status=JobStatus.cancelled, completed_at=utcnow())
        )
        await emit_event(
            session,
            event_type=ExecutionEvents.run_cancelled.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={"run_record_id": str(run.id)},
            actor_type=actor_type,
            actor_id=actor_id,
        )
        if run.workspace_path:
            settings = get_settings()
            cleanup_worktree(settings.repo_root, Path(run.workspace_path))
        if run.container_id:
            DockerRunner().kill(run.container_id)

    elif action == "pause":
        run.status = "paused"
        run.updated_at = utcnow()
        from sqlalchemy import update as sa_update

        await session.execute(
            sa_update(Job)
            .where(
                Job.status.in_([JobStatus.claimed.value, JobStatus.running.value]),
                Job.payload["run_record_id"].astext == str(run_id),
            )
            .values(status=JobStatus.paused)
        )
        await emit_event(
            session,
            event_type=ExecutionEvents.run_paused.value,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            payload={"run_record_id": str(run.id)},
            actor_type=actor_type,
            actor_id=actor_id,
        )

    elif action == "resume":
        run.status = "running"
        run.updated_at = utcnow()
        # Enqueue a new execution_run job with resume flag
        job_id = uuid7()
        job = Job(
            id=job_id,
            cycle_id=run.cycle_id,
            job_type="execution_run",
            status=JobStatus.pending,
            payload={"run_record_id": str(run.id), "resume": True},
            priority=10,
            created_at=utcnow(),
        )
        session.add(job)
        cycle = await session.get(ResearchCycle, run.cycle_id)
        if cycle is not None and cycle.status != CycleStatus.running:
            cycle.status = CycleStatus.running
            cycle.updated_at = utcnow()

    elif action == "retry":
        # Create a new RunRecord — old one stays immutable
        existing_count_result = await session.execute(
            select(func.count(RunRecord.id)).where(
                RunRecord.experiment_spec_id == run.experiment_spec_id
            )
        )
        new_run_number = (existing_count_result.scalar() or 0) + 1

        new_run = RunRecord(
            id=uuid7(),
            experiment_spec_id=run.experiment_spec_id,
            charter_id=run.charter_id,
            cycle_id=run.cycle_id,
            run_number=new_run_number,
            status="pending",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(new_run)
        await session.flush()

        cycle = await session.get(ResearchCycle, run.cycle_id)
        if cycle is not None and cycle.status != CycleStatus.running:
            cycle.status = CycleStatus.running
            cycle.updated_at = utcnow()

        job_id = uuid7()
        job = Job(
            id=job_id,
            cycle_id=run.cycle_id,
            job_type="execution_setup",
            status=JobStatus.pending,
            payload={"run_record_id": str(new_run.id)},
            priority=10,
            created_at=utcnow(),
        )
        session.add(job)

        await session.flush()
        # Return the new run, not the old one
        return RunRecordRead.model_validate(new_run)

    await session.flush()
    return RunRecordRead.model_validate(run)


# ---------------------------------------------------------------------------
# Run telemetry
# ---------------------------------------------------------------------------


async def list_run_telemetry(
    session: AsyncSession,
    run_id: UUID,
    *,
    since: UUID | None = None,
    limit: int = 100,
) -> list[RunTelemetryRead]:
    query = select(RunTelemetry).where(RunTelemetry.run_record_id == run_id)
    if since is not None:
        query = query.where(RunTelemetry.id > since)
    result = await session.execute(
        query.order_by(RunTelemetry.timestamp.asc()).limit(limit)
    )
    return [RunTelemetryRead.model_validate(t) for t in result.scalars().all()]


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


async def get_verification_report(
    session: AsyncSession,
    run_id: UUID,
) -> VerificationReportRead | None:
    result = await session.execute(
        select(VerificationReport).where(VerificationReport.run_record_id == run_id)
    )
    obj = result.scalar_one_or_none()
    return VerificationReportRead.model_validate(obj) if obj else None


async def get_failure_postmortem(
    session: AsyncSession,
    run_id: UUID,
) -> FailurePostmortemRead | None:
    result = await session.execute(
        select(FailurePostmortem).where(FailurePostmortem.run_record_id == run_id)
    )
    obj = result.scalar_one_or_none()
    return FailurePostmortemRead.model_validate(obj) if obj else None


async def list_verification_reports(
    session: AsyncSession,
    *,
    cycle_id: UUID | None = None,
    verdict: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[VerificationReportRead], int]:
    query = select(VerificationReport)
    count_query = select(func.count(VerificationReport.id))

    if cycle_id is not None:
        query = query.where(VerificationReport.cycle_id == cycle_id)
        count_query = count_query.where(VerificationReport.cycle_id == cycle_id)
    if verdict is not None:
        query = query.where(VerificationReport.verdict == verdict)
        count_query = count_query.where(VerificationReport.verdict == verdict)

    total = (await session.execute(count_query)).scalar() or 0
    result = await session.execute(
        query.order_by(VerificationReport.created_at.desc()).offset(offset).limit(limit)
    )
    items = [VerificationReportRead.model_validate(r) for r in result.scalars().all()]
    return items, total
