from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.config import AppConfig
from libs.core.ids import generate_public_id
from libs.core.operators import OperatorResult
from libs.core.policy import Actor, TokenScope
from libs.core.state_machine import CycleStatus, ensure_transition
from libs.schemas.api import (
    CreateCycleRequest,
    CycleDetailResponse,
    CycleSummaryResponse,
    JobDetailResponse,
    ReportDetailResponse,
    ReportSummary,
    SkillDetailResponse,
    SkillSummaryResponse,
)
from libs.schemas.domain import (
    DomainEventEnvelope,
    JobRecord,
    ResearchCharter,
    ResearchCycle,
    ResearchStateSnapshot,
    SkillBinding,
    SkillDefinition,
    SkillExecutionRecord,
    SkillVersion,
)
from libs.skills.loader import load_all_skills
from libs.storage.models import (
    DomainEventModel,
    JobModel,
    OrchestratorClientModel,
    OrchestratorCommandModel,
    OrchestratorTokenModel,
    ReportBundleModel,
    ResearchCharterModel,
    ResearchCycleModel,
    ResearchStateSnapshotModel,
    SkillBindingModel,
    SkillDefinitionModel,
    SkillExecutionRecordModel,
    SkillValidationIssueModel,
    SkillVersionModel,
)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def seed_dev_client_and_token(session: Session, config: AppConfig) -> None:
    client = session.scalar(
        select(OrchestratorClientModel).where(OrchestratorClientModel.name == "local-dev")
    )
    if client is None:
        client = OrchestratorClientModel(
            public_id=generate_public_id("orch"),
            name="local-dev",
            description="Seeded local development client",
            is_active=True,
        )
        session.add(client)
        session.flush()
    existing = session.scalar(
        select(OrchestratorTokenModel).where(
            OrchestratorTokenModel.token_hash == token_hash(config.dev_admin_token)
        )
    )
    if existing is None:
        session.add(
            OrchestratorTokenModel(
                public_id=generate_public_id("token"),
                client_id=client.id,
                token_hash=token_hash(config.dev_admin_token),
                scopes=[scope.value for scope in TokenScope],
            )
        )
    session.commit()


def authenticate_token(session: Session, raw_token: str) -> Actor | None:
    hashed = token_hash(raw_token)
    token = session.scalar(
        select(OrchestratorTokenModel).where(OrchestratorTokenModel.token_hash == hashed)
    )
    if token is None:
        return None
    client = session.get(OrchestratorClientModel, token.client_id)
    if client is None or not client.is_active:
        return None
    token.last_used_at = datetime.now(UTC)
    session.flush()
    return Actor(
        actor_id=f"orchestrator:{client.public_id}",
        client_id=client.public_id,
        scopes=frozenset(TokenScope(scope) for scope in token.scopes),
    )


def create_state_snapshot(
    session: Session,
    cycle: ResearchCycleModel,
    target_state: CycleStatus,
    actor: Actor,
    reason: str,
    context: dict[str, Any] | None = None,
    scope_used: str | None = None,
) -> ResearchStateSnapshotModel:
    current = CycleStatus(cycle.current_status)
    ensure_transition(current, target_state)
    snapshot = ResearchStateSnapshotModel(
        public_id=generate_public_id("state"),
        cycle_id=cycle.id,
        state=target_state.value,
        transition_reason=reason,
        context=context or {},
        actor_id=actor.actor_id,
        scope_used=scope_used,
    )
    cycle.current_status = target_state.value
    session.add(snapshot)
    session.flush()
    cycle.current_state_snapshot_id = snapshot.id
    return snapshot


def append_event(
    session: Session,
    *,
    actor: Actor,
    event_type: str,
    payload: dict[str, Any],
    cycle_id: int | None = None,
    job_id: int | None = None,
    scope_used: str | None = None,
) -> DomainEventModel:
    event = DomainEventModel(
        public_id=generate_public_id("evt"),
        cycle_id=cycle_id,
        job_id=job_id,
        actor_id=actor.actor_id,
        scope_used=scope_used,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    session.flush()
    return event


def create_cycle(session: Session, actor: Actor, payload: CreateCycleRequest) -> ResearchCycleModel:
    charter = ResearchCharterModel(
        public_id=generate_public_id("charter"),
        **payload.model_dump(mode="python"),
    )
    session.add(charter)
    session.flush()

    cycle = ResearchCycleModel(
        public_id=generate_public_id("cycle"),
        charter_id=charter.id,
        current_status=CycleStatus.CREATED.value,
    )
    session.add(cycle)
    session.flush()

    created_snapshot = ResearchStateSnapshotModel(
        public_id=generate_public_id("state"),
        cycle_id=cycle.id,
        state=CycleStatus.CREATED.value,
        transition_reason="Cycle created",
        context={"title": charter.title},
        actor_id=actor.actor_id,
        scope_used=TokenScope.CYCLES_WRITE.value,
    )
    session.add(created_snapshot)
    session.flush()
    cycle.current_state_snapshot_id = created_snapshot.id

    append_event(
        session,
        actor=actor,
        event_type="research_cycle_created",
        payload={"cycle_public_id": cycle.public_id, "charter_public_id": charter.public_id},
        cycle_id=cycle.id,
        scope_used=TokenScope.CYCLES_WRITE.value,
    )

    cycle.current_status = CycleStatus.QUEUED.value
    queued_snapshot = ResearchStateSnapshotModel(
        public_id=generate_public_id("state"),
        cycle_id=cycle.id,
        state=CycleStatus.QUEUED.value,
        transition_reason="Initialization job enqueued",
        context={},
        actor_id=actor.actor_id,
        scope_used=TokenScope.CYCLES_WRITE.value,
    )
    session.add(queued_snapshot)
    session.flush()
    cycle.current_state_snapshot_id = queued_snapshot.id
    append_event(
        session,
        actor=actor,
        event_type="research_cycle_queued",
        payload={"cycle_public_id": cycle.public_id},
        cycle_id=cycle.id,
        scope_used=TokenScope.CYCLES_WRITE.value,
    )
    return cycle


def get_cycle_by_public_id(session: Session, cycle_public_id: str) -> ResearchCycleModel:
    cycle = session.scalar(
        select(ResearchCycleModel).where(
            ResearchCycleModel.public_id == cycle_public_id
        )
    )
    if cycle is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return cycle


def get_job_by_public_id(session: Session, job_public_id: str) -> JobModel:
    job = session.scalar(select(JobModel).where(JobModel.public_id == job_public_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def sync_skill_catalog(session: Session, config: AppConfig) -> None:
    loaded = load_all_skills(config.skill_paths)
    session.query(SkillValidationIssueModel).delete()
    for item in loaded:
        definition = session.scalar(
            select(SkillDefinitionModel).where(SkillDefinitionModel.skill_key == item.skill_key)
        )
        if definition is None:
            definition = SkillDefinitionModel(
                public_id=generate_public_id("skill"),
                skill_key=item.skill_key,
                phase=item.phase,
                is_active=item.is_valid,
            )
            session.add(definition)
            session.flush()
        else:
            definition.phase = item.phase
            definition.is_active = item.is_valid
        if item.is_valid:
            version = session.scalar(
                select(SkillVersionModel).where(
                    SkillVersionModel.definition_id == definition.id,
                    SkillVersionModel.version == item.version,
                )
            )
            if version is None:
                version = SkillVersionModel(
                    public_id=generate_public_id("skillver"),
                    definition_id=definition.id,
                    version=item.version,
                    content_hash=item.content_hash,
                    manifest=item.manifest.model_dump(mode="python"),
                    body_markdown=item.body_markdown,
                    hooks_path=str(item.hooks_path) if item.hooks_path else None,
                    hook_exports=item.hook_exports,
                    is_valid=True,
                )
                session.add(version)
            else:
                version.content_hash = item.content_hash
                version.manifest = item.manifest.model_dump(mode="python")
                version.body_markdown = item.body_markdown
                version.hooks_path = str(item.hooks_path) if item.hooks_path else None
                version.hook_exports = item.hook_exports
                version.is_valid = True
        else:
            for issue in item.validation_issues:
                session.add(
                    SkillValidationIssueModel(
                        public_id=generate_public_id("skillissue"),
                        skill_definition_id=definition.id,
                        path=str(item.path),
                        severity=issue["severity"],
                        message=issue["message"],
                        details=issue.get("details", {}),
                    )
                )
    session.commit()


def resolve_skill_versions_for_operator(
    session: Session,
    operator_name: str,
) -> list[SkillVersionModel]:
    versions = session.scalars(select(SkillVersionModel).join(SkillDefinitionModel)).all()
    matches: list[SkillVersionModel] = []
    for version in versions:
        if not version.is_valid:
            continue
        allowed = version.manifest.get("allowed_operators", [])
        if operator_name in allowed:
            matches.append(version)
    return matches


def bind_skills_for_cycle(
    session: Session,
    cycle: ResearchCycleModel,
    operator_name: str,
) -> list[SkillBindingModel]:
    bindings: list[SkillBindingModel] = []
    for version in resolve_skill_versions_for_operator(session, operator_name):
        binding = session.scalar(
            select(SkillBindingModel).where(
                SkillBindingModel.cycle_id == cycle.id,
                SkillBindingModel.skill_version_id == version.id,
                SkillBindingModel.operator_name == operator_name,
            )
        )
        if binding is None:
            binding = SkillBindingModel(
                public_id=generate_public_id("bind"),
                cycle_id=cycle.id,
                skill_version_id=version.id,
                operator_name=operator_name,
                binding_reason="Eligible for operator during Phase 0 initialization",
                is_active=True,
            )
            session.add(binding)
            session.flush()
        bindings.append(binding)
    return bindings


def create_report(
    session: Session,
    config: AppConfig,
    *,
    cycle: ResearchCycleModel,
    job: JobModel,
    title: str,
    report_type: str,
    body_markdown: str,
) -> ReportBundleModel:
    public_id = generate_public_id("report")
    path = config.reports_dir / f"{public_id}.md"
    path.write_text(body_markdown, encoding="utf-8")
    report = ReportBundleModel(
        public_id=public_id,
        cycle_id=cycle.id,
        job_id=job.id,
        report_type=report_type,
        title=title,
        artifact_path=str(path),
        report_metadata={"format": "markdown"},
    )
    session.add(report)
    session.flush()
    return report


def apply_operator_result(
    session: Session,
    *,
    cycle: ResearchCycleModel,
    job: JobModel,
    actor: Actor,
    result: OperatorResult,
    config: AppConfig,
) -> None:
    create_state_snapshot(
        session,
        cycle=cycle,
        target_state=result.state_patch.target_state,
        actor=actor,
        reason=result.state_patch.reason,
        context=result.state_patch.context,
    )
    for event in result.emitted_events:
        append_event(
            session,
            actor=actor,
            event_type=event["event_type"],
            payload=event["payload"],
            cycle_id=cycle.id,
            job_id=job.id,
        )
    report = create_report(
        session,
        config,
        cycle=cycle,
        job=job,
        title=result.operator_report.title,
        report_type="operator_report",
        body_markdown=result.operator_report.body_markdown,
    )
    append_event(
        session,
        actor=actor,
        event_type="report_bundle_created",
        payload={"report_public_id": report.public_id, "title": report.title},
        cycle_id=cycle.id,
        job_id=job.id,
    )
    for outcome in result.skill_execution_records:
        session.add(
            SkillExecutionRecordModel(
                public_id=generate_public_id("skillexec"),
                cycle_id=cycle.id,
                job_id=job.id,
                skill_binding_id=_binding_id_from_public_id(
                    session, outcome.skill_binding_public_id,
                ),
                operator_name=outcome.operator_name,
                status=outcome.status,
                payload=outcome.payload,
            )
        )
    append_event(
        session,
        actor=actor,
        event_type="job_succeeded",
        payload={"job_public_id": job.public_id, "operator_name": job.operator_name},
        cycle_id=cycle.id,
        job_id=job.id,
    )


def _binding_id_from_public_id(session: Session, binding_public_id: str) -> int:
    binding = session.scalar(
        select(SkillBindingModel).where(
            SkillBindingModel.public_id == binding_public_id
        )
    )
    if binding is None:
        raise ValueError(f"Missing skill binding {binding_public_id}")
    return binding.id


def build_cycle_detail(session: Session, cycle_public_id: str) -> CycleDetailResponse:
    cycle = get_cycle_by_public_id(session, cycle_public_id)
    charter = session.get(ResearchCharterModel, cycle.charter_id)
    snapshot = (
        session.get(ResearchStateSnapshotModel, cycle.current_state_snapshot_id)
        if cycle.current_state_snapshot_id
        else None
    )
    jobs = session.scalars(
        select(JobModel)
        .where(JobModel.cycle_id == cycle.id)
        .order_by(JobModel.created_at.desc())
        .limit(10)
    ).all()
    events = session.scalars(
        select(DomainEventModel)
        .where(DomainEventModel.cycle_id == cycle.id)
        .order_by(DomainEventModel.sequence_id.desc())
        .limit(20)
    ).all()
    bindings = session.scalars(
        select(SkillBindingModel)
        .where(SkillBindingModel.cycle_id == cycle.id)
        .order_by(SkillBindingModel.created_at.desc())
    ).all()
    execs = session.scalars(
        select(SkillExecutionRecordModel)
        .where(SkillExecutionRecordModel.cycle_id == cycle.id)
        .order_by(SkillExecutionRecordModel.created_at.desc())
    ).all()
    reports = session.scalars(
        select(ReportBundleModel)
        .where(ReportBundleModel.cycle_id == cycle.id)
        .order_by(ReportBundleModel.created_at.desc())
    ).all()

    # Build job lookup to avoid N+1 queries
    job_ids = {j.id: j.public_id for j in jobs}
    event_job_ids = {e.job_id for e in events if e.job_id}
    missing_job_ids = event_job_ids - set(job_ids.keys())
    if missing_job_ids:
        extra_jobs = session.scalars(
            select(JobModel).where(JobModel.id.in_(missing_job_ids))
        ).all()
        for j in extra_jobs:
            job_ids[j.id] = j.public_id

    event_models = [
        DomainEventEnvelope(
            sequence_id=event.sequence_id,
            public_id=event.public_id,
            cycle_public_id=cycle.public_id if event.cycle_id else None,
            job_public_id=job_ids.get(event.job_id) if event.job_id else None,
            actor_id=event.actor_id,
            scope_used=event.scope_used,
            event_type=event.event_type,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]

    return CycleDetailResponse(
        cycle=ResearchCycle.model_validate(cycle),
        charter=ResearchCharter.model_validate(charter),
        current_state_snapshot=ResearchStateSnapshot.model_validate(snapshot) if snapshot else None,
        recent_jobs=[JobRecord.model_validate(job) for job in jobs],
        recent_events=event_models,
        bound_skills=[SkillBinding.model_validate(binding) for binding in bindings],
        skill_execution_records=[SkillExecutionRecord.model_validate(item) for item in execs],
        reports=[
            ReportSummary(
                public_id=report.public_id,
                cycle_public_id=cycle.public_id,
                report_type=report.report_type,
                title=report.title,
                artifact_path=report.artifact_path,
                created_at=report.created_at,
            )
            for report in reports
        ],
    )


def list_cycles(session: Session) -> list[CycleSummaryResponse]:
    cycles = session.scalars(
        select(ResearchCycleModel)
        .order_by(ResearchCycleModel.created_at.desc())
    ).all()
    items: list[CycleSummaryResponse] = []
    for cycle in cycles:
        charter = session.get(ResearchCharterModel, cycle.charter_id)
        snapshot = (
            session.get(ResearchStateSnapshotModel, cycle.current_state_snapshot_id)
            if cycle.current_state_snapshot_id
            else None
        )
        items.append(
            CycleSummaryResponse(
                cycle=ResearchCycle.model_validate(cycle),
                charter=ResearchCharter.model_validate(charter),
                state_snapshot=ResearchStateSnapshot.model_validate(snapshot) if snapshot else None,
            )
        )
    return items


def list_jobs(session: Session) -> list[JobRecord]:
    return [
        JobRecord.model_validate(job)
        for job in session.scalars(select(JobModel).order_by(JobModel.created_at.desc())).all()
    ]


def get_job_detail(session: Session, job_public_id: str) -> JobDetailResponse:
    job = get_job_by_public_id(session, job_public_id)
    return JobDetailResponse(job=JobRecord.model_validate(job))


def list_skills(session: Session) -> list[SkillSummaryResponse]:
    definitions = session.scalars(
        select(SkillDefinitionModel)
        .order_by(SkillDefinitionModel.skill_key)
    ).all()
    items: list[SkillSummaryResponse] = []
    for definition in definitions:
        version = session.scalar(
            select(SkillVersionModel)
            .where(SkillVersionModel.definition_id == definition.id)
            .order_by(SkillVersionModel.created_at.desc())
        )
        items.append(
            SkillSummaryResponse(
                definition=SkillDefinition.model_validate(definition),
                latest_version=SkillVersion.model_validate(version) if version else None,
            )
        )
    return items


def get_skill_detail(session: Session, skill_public_id: str) -> SkillDetailResponse:
    definition = session.scalar(
        select(SkillDefinitionModel).where(SkillDefinitionModel.public_id == skill_public_id)
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    versions = session.scalars(
        select(SkillVersionModel)
        .where(SkillVersionModel.definition_id == definition.id)
        .order_by(SkillVersionModel.created_at.desc())
    ).all()
    issues = session.scalars(
        select(SkillValidationIssueModel).where(
            SkillValidationIssueModel.skill_definition_id == definition.id
        )
    ).all()
    return SkillDetailResponse(
        definition=SkillDefinition.model_validate(definition),
        versions=[SkillVersion.model_validate(version) for version in versions],
        validation_issues=[
            {
                "public_id": issue.public_id,
                "path": issue.path,
                "severity": issue.severity,
                "message": issue.message,
                "details": issue.details,
            }
            for issue in issues
        ],
    )


def list_reports(session: Session) -> list[ReportSummary]:
    all_cycles = session.scalars(select(ResearchCycleModel)).all()
    cycles = {c.id: c.public_id for c in all_cycles}
    reports = session.scalars(
        select(ReportBundleModel)
        .order_by(ReportBundleModel.created_at.desc())
    ).all()
    return [
        ReportSummary(
            public_id=report.public_id,
            cycle_public_id=cycles.get(report.cycle_id),
            report_type=report.report_type,
            title=report.title,
            artifact_path=report.artifact_path,
            created_at=report.created_at,
        )
        for report in reports
    ]


def get_report_detail(session: Session, report_public_id: str) -> ReportDetailResponse:
    report = session.scalar(
        select(ReportBundleModel).where(
            ReportBundleModel.public_id == report_public_id
        )
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    cycle = session.get(ResearchCycleModel, report.cycle_id) if report.cycle_id else None
    markdown = Path(report.artifact_path).read_text(encoding="utf-8")
    return ReportDetailResponse(
        public_id=report.public_id,
        cycle_public_id=cycle.public_id if cycle else None,
        report_type=report.report_type,
        title=report.title,
        artifact_path=report.artifact_path,
        created_at=report.created_at,
        markdown=markdown,
    )


def list_events_after(
    session: Session,
    last_event_id: int,
    cycle_id: str | None = None,
) -> list[DomainEventEnvelope]:
    cycle_db_id: int | None = None
    if cycle_id is not None:
        cycle = get_cycle_by_public_id(session, cycle_id)
        cycle_db_id = cycle.id
    query = select(DomainEventModel).where(DomainEventModel.sequence_id > last_event_id)
    if cycle_db_id is not None:
        query = query.where(DomainEventModel.cycle_id == cycle_db_id)
    events = session.scalars(
        query.order_by(DomainEventModel.sequence_id.asc()).limit(100)
    ).all()

    # Only look up IDs referenced by these events
    job_ids = {e.job_id for e in events if e.job_id}
    cycle_ids = {e.cycle_id for e in events if e.cycle_id}
    jobs: dict[int, str] = {}
    if job_ids:
        for j in session.scalars(
            select(JobModel).where(JobModel.id.in_(job_ids))
        ).all():
            jobs[j.id] = j.public_id
    cycles: dict[int, str] = {}
    if cycle_ids:
        for c in session.scalars(
            select(ResearchCycleModel).where(
                ResearchCycleModel.id.in_(cycle_ids)
            )
        ).all():
            cycles[c.id] = c.public_id
    return [
        DomainEventEnvelope(
            sequence_id=event.sequence_id,
            public_id=event.public_id,
            cycle_public_id=cycles.get(event.cycle_id),
            job_public_id=jobs.get(event.job_id),
            actor_id=event.actor_id,
            scope_used=event.scope_used,
            event_type=event.event_type,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]


def record_command(
    session: Session,
    *,
    actor: Actor,
    command_name: str,
    target_resource: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    cycle_id: int | None = None,
    cycle_public_id: str | None = None,
) -> None:
    if cycle_public_id and cycle_id is None:
        cycle_id = get_cycle_by_public_id(session, cycle_public_id).id
    client = session.scalar(
        select(OrchestratorClientModel).where(OrchestratorClientModel.public_id == actor.client_id)
    )
    if client is None:
        return
    session.add(
        OrchestratorCommandModel(
            public_id=generate_public_id("cmd"),
            client_id=client.id,
            cycle_id=cycle_id,
            actor_id=actor.actor_id,
            scope_used=",".join(sorted(scope.value for scope in actor.scopes)),
            command_name=command_name,
            target_resource=target_resource,
            payload=payload,
            result=result,
        )
    )


def apply_cycle_command(session: Session, actor: Actor, cycle_public_id: str, command: str) -> None:
    cycle = get_cycle_by_public_id(session, cycle_public_id)
    current = CycleStatus(cycle.current_status)
    if command == "pause":
        target = CycleStatus.PAUSED
    elif command == "cancel":
        target = (
            CycleStatus.CANCEL_REQUESTED
            if current in {
                CycleStatus.QUEUED, CycleStatus.INITIALIZING,
                CycleStatus.READY, CycleStatus.PAUSED,
            }
            else CycleStatus.CANCELLED
        )
    elif command == "resume":
        target = CycleStatus.QUEUED if _has_pending_jobs(session, cycle.id) else CycleStatus.READY
    else:
        raise HTTPException(status_code=400, detail="Unsupported command")
    ensure_transition(current, target)
    create_state_snapshot(
        session,
        cycle=cycle,
        target_state=target,
        actor=actor,
        reason=f"Cycle command applied: {command}",
        context={"command": command},
        scope_used=TokenScope.RUNS_CONTROL.value,
    )
    append_event(
        session,
        actor=actor,
        event_type="orchestrator_command_received",
        payload={"cycle_public_id": cycle.public_id, "command": command},
        cycle_id=cycle.id,
        scope_used=TokenScope.RUNS_CONTROL.value,
    )


def _has_pending_jobs(session: Session, cycle_id: int) -> bool:
    job = session.scalar(
        select(JobModel).where(
            JobModel.cycle_id == cycle_id,
            JobModel.status.in_(["pending", "claimed"]),
        )
    )
    return job is not None
