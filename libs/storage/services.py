from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.core.config import AppConfig
from libs.core.ids import generate_public_id
from libs.core.operators import OperatorResult
from libs.core.policy import Actor, TokenScope
from libs.core.state_machine import CycleStatus, ensure_transition
from libs.execution.policy import evaluate_run_policy
from libs.execution.runner import build_run_spec, determine_run_paths, load_execution_profile
from libs.schemas.api import (
    CreateCycleRequest,
    CycleDetailResponse,
    CycleSummaryResponse,
    EvidenceCardDetail,
    EvidenceCardSummary,
    EvidenceListResponse,
    EvidenceSummaryResponse,
    ExperimentSpecDetail,
    ExperimentSpecListResponse,
    ExperimentSpecSummary,
    FailurePostmortemDetail,
    FailurePostmortemListResponse,
    FailurePostmortemSummary,
    HistoricalComparisonResponse,
    HypothesisCardDetail,
    HypothesisCardSummary,
    HypothesisListResponse,
    JobDetailResponse,
    LiteratureTriageResponse,
    PaperCardDetail,
    PaperCardSummary,
    PortfolioRankingResponse,
    ReportDetailResponse,
    ReportSummary,
    RunArtifactManifest,
    RunCreateRequest,
    RunDetailResponse,
    RunListResponse,
    RunSummary,
    RunTelemetryEvent,
    SkillDetailResponse,
    SkillSummaryResponse,
    VerificationReportDetail,
    VerificationReportListResponse,
    VerificationReportSummary,
    VerificationSummaryResponse,
)
from libs.schemas.domain import (
    DomainEventEnvelope,
    JobRecord,
    ResearchCharter,
    ResearchCycle,
    ResearchStateSnapshot,
    RunRecord,
    RunSpec,
    SkillBinding,
    SkillDefinition,
    SkillExecutionRecord,
    SkillVersion,
)
from libs.skills.loader import load_all_skills
from libs.storage.models import (
    DomainEventModel,
    ExperimentSpecModel,
    FailurePostmortemModel,
    JobModel,
    ModelInvocationRecordModel,
    OrchestratorClientModel,
    OrchestratorCommandModel,
    OrchestratorTokenModel,
    ReportBundleModel,
    ResearchCharterModel,
    ResearchCycleModel,
    ResearchStateSnapshotModel,
    RunRecordModel,
    RunTelemetryEventModel,
    SkillBindingModel,
    SkillDefinitionModel,
    SkillExecutionRecordModel,
    SkillValidationIssueModel,
    SkillVersionModel,
    VerificationReportModel,
)
from libs.verification.historical import collect_historical_memory_refs, find_comparable_runs
from libs.verification.recommendations import build_next_step_recommendations

DEFAULT_SOURCE_SCOPE: dict[str, Any] = {
    "mode": "internal+arxiv",
    "keywords": [],
    "categories": ["cs"],
    "date_from": None,
    "date_until": None,
    "max_results": 50,
    "fulltext_budget": {"max_fetches": 3},
}


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_source_scope(source_scope: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(source_scope or {})
    merged = {
        **DEFAULT_SOURCE_SCOPE,
        **raw,
    }

    def _split_csv(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[,\n]", value) if item.strip()]
        return []

    keywords = _split_csv(merged.get("keywords"))
    categories = _split_csv(merged.get("categories")) or ["cs"]

    budget_raw = merged.get("fulltext_budget")
    if isinstance(budget_raw, int):
        fulltext_budget = {"max_fetches": max(0, budget_raw)}
    elif isinstance(budget_raw, dict):
        default_max_fetches = DEFAULT_SOURCE_SCOPE["fulltext_budget"]["max_fetches"]
        max_fetches = budget_raw.get("max_fetches", default_max_fetches)
        try:
            max_fetches = int(max_fetches)
        except (TypeError, ValueError):
            max_fetches = default_max_fetches
        fulltext_budget = {**budget_raw, "max_fetches": max(0, max_fetches)}
    else:
        fulltext_budget = dict(DEFAULT_SOURCE_SCOPE["fulltext_budget"])

    try:
        max_results = int(merged.get("max_results", DEFAULT_SOURCE_SCOPE["max_results"]))
    except (TypeError, ValueError):
        max_results = DEFAULT_SOURCE_SCOPE["max_results"]

    return {
        **merged,
        "keywords": keywords,
        "categories": categories,
        "max_results": max(1, max_results),
        "fulltext_budget": fulltext_budget,
    }


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
    charter_payload = payload.model_dump(mode="python")
    charter_payload["source_scope"] = normalize_source_scope(charter_payload.get("source_scope"))
    charter = ResearchCharterModel(
        public_id=generate_public_id("charter"),
        **charter_payload,
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
                binding_reason=f"Eligible for operator `{operator_name}` based on skill manifest",
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
    from libs.reporting.scoring import score_report_structure

    public_id = generate_public_id("report")
    path = config.reports_dir / f"{public_id}.md"
    path.write_text(body_markdown, encoding="utf-8")
    quality = score_report_structure(body_markdown, report_type)
    report = ReportBundleModel(
        public_id=public_id,
        cycle_id=cycle.id,
        job_id=job.id,
        report_type=report_type,
        title=title,
        artifact_path=str(path),
        report_metadata={"format": "markdown"},
        quality_metadata=quality,
    )
    session.add(report)
    session.flush()
    return report


def get_cycle_timeline(
    session: Session,
    cycle_public_id: str,
) -> list[dict]:
    """Return a chronologically ordered timeline of events for a cycle."""
    cycle = get_cycle_by_public_id(session, cycle_public_id)
    events = session.scalars(
        select(DomainEventModel)
        .where(DomainEventModel.cycle_id == cycle.id)
        .order_by(DomainEventModel.created_at.asc())
    ).all()

    timeline: list[dict] = []
    for event in events:
        category, summary = _categorize_event(event.event_type, event.payload)
        timeline.append({
            "timestamp": event.created_at.isoformat(),
            "event_type": event.event_type,
            "category": category,
            "summary": summary,
            "details": event.payload or {},
        })
    return timeline


_EVENT_CATEGORIES: dict[str, str] = {
    "cycle_created": "state_change",
    "state_snapshot_created": "state_change",
    "job_enqueued": "operator",
    "job_claimed": "operator",
    "job_failed": "operator",
    "operator_result_applied": "operator",
    "run_command_received": "run",
    "run_created": "run",
    "report_created": "report",
    "skill_execution_recorded": "operator",
    "model_invocation_recorded": "operator",
}


def _categorize_event(event_type: str, payload: dict) -> tuple[str, str]:
    category = _EVENT_CATEGORIES.get(event_type, "system")
    summary = event_type.replace("_", " ").capitalize()

    if event_type == "state_snapshot_created":
        state = payload.get("state", "")
        reason = payload.get("reason", "")
        summary = f"Cycle → {state}" + (f": {reason}" if reason else "")
    elif event_type == "job_claimed":
        op = payload.get("operator_name", "")
        summary = f"Started operator: {op}"
    elif event_type == "job_failed":
        error = payload.get("error", "unknown")
        summary = f"Job failed: {error[:80]}"
    elif event_type == "run_command_received":
        cmd = payload.get("command", "")
        summary = f"Run command: {cmd}"
    elif event_type == "report_created":
        title = payload.get("title", "report")
        summary = f"Report generated: {title}"

    return category, summary


def record_model_invocation(
    session: Session,
    *,
    cycle_id: int | None,
    job_id: int | None,
    run_record_id: int | None = None,
    route_id: str,
    model_id: str,
    prompt_id: str,
    parameters: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> ModelInvocationRecordModel:
    record = ModelInvocationRecordModel(
        public_id=generate_public_id("modelinv"),
        cycle_id=cycle_id,
        job_id=job_id,
        run_record_id=run_record_id,
        route_id=route_id,
        model_id=model_id,
        prompt_id=prompt_id,
        parameters=parameters or {},
        usage=usage or {},
    )
    session.add(record)
    session.flush()
    return record


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
        report_type=result.operator_report.report_type,
        body_markdown=result.operator_report.body_markdown,
    )
    run_public_id = result.state_patch.context.get("run_public_id")
    if run_public_id:
        report.report_metadata = {
            **(report.report_metadata or {}),
            "run_public_id": run_public_id,
        }
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
                run_record_id=_run_id_from_public_id(session, outcome.run_public_id)
                if outcome.run_public_id
                else None,
                skill_binding_id=_binding_id_from_public_id(
                    session, outcome.skill_binding_public_id,
                ),
                operator_name=outcome.operator_name,
                status=outcome.status,
                payload=outcome.payload,
            )
        )
    from libs.orchestration.job_queue import enqueue_job as _enqueue

    for action in result.next_actions:
        _enqueue(
            session, actor, cycle.id,
            action.action, action.payload,
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


def _run_id_from_public_id(session: Session, run_public_id: str) -> int:
    run = session.scalar(
        select(RunRecordModel).where(RunRecordModel.public_id == run_public_id)
    )
    if run is None:
        raise ValueError(f"Missing run record {run_public_id}")
    return run.id


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
    run_ids = {item.run_record_id for item in execs if item.run_record_id}
    runs = {}
    if run_ids:
        run_query = select(RunRecordModel).where(RunRecordModel.id.in_(run_ids))
        for run in session.scalars(run_query).all():
            runs[run.id] = run.public_id

    return CycleDetailResponse(
        cycle=ResearchCycle.model_validate(cycle),
        charter=ResearchCharter.model_validate(charter),
        current_state_snapshot=ResearchStateSnapshot.model_validate(snapshot) if snapshot else None,
        recent_jobs=[JobRecord.model_validate(job) for job in jobs],
        recent_events=event_models,
        bound_skills=[SkillBinding.model_validate(binding) for binding in bindings],
        skill_execution_records=[
            SkillExecutionRecord(
                public_id=item.public_id,
                operator_name=item.operator_name,
                status=item.status,
                run_public_id=runs.get(item.run_record_id),
                payload=item.payload,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in execs
        ],
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
        quality_metadata=report.quality_metadata or {},
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


def apply_cycle_command(
    session: Session, actor: Actor, cycle_public_id: str, command: str,
    payload: dict | None = None,
) -> None:
    cycle = get_cycle_by_public_id(session, cycle_public_id)
    current = CycleStatus(cycle.current_status)
    if command == "pause":
        target = CycleStatus.PAUSED
    elif command == "cancel":
        target = (
            CycleStatus.CANCEL_REQUESTED
            if current in {
                CycleStatus.QUEUED, CycleStatus.INITIALIZING, CycleStatus.RUNNING,
                CycleStatus.READY, CycleStatus.PAUSED,
            }
            else CycleStatus.CANCELLED
        )
    elif command == "resume":
        target = CycleStatus.QUEUED if _has_pending_jobs(session, cycle.id) else CycleStatus.READY
    elif command == "start_intake":
        if current != CycleStatus.READY:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot start intake from state {current.value}; cycle must be READY",
            )
        charter = session.get(ResearchCharterModel, cycle.charter_id)
        source_scope = charter.source_scope if charter else {}
        job_payload = {
            "cycle_public_id": cycle.public_id,
            "source_scope": source_scope,
        }
        if payload:
            job_payload["source_overrides"] = payload
        from libs.orchestration.job_queue import enqueue_job as _enqueue_job
        _enqueue_job(session, actor, cycle.id, "source_retrieval", job_payload)
        target = CycleStatus.QUEUED
    elif command == "start_evidence":
        if current != CycleStatus.READY:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot start evidence from state {current.value}; cycle must be READY",
            )
        job_payload: dict = {"cycle_public_id": cycle.public_id}
        if payload:
            job_payload.update(payload)
        from libs.orchestration.job_queue import enqueue_job as _enqueue_job
        _enqueue_job(session, actor, cycle.id, "evidence_extraction", job_payload)
        target = CycleStatus.QUEUED
    elif command == "request_hypothesis_review":
        if current != CycleStatus.READY:
            raise HTTPException(status_code=400, detail="Cycle must be READY")
        from libs.orchestration.job_queue import enqueue_job as _enqueue_job
        _enqueue_job(
            session, actor, cycle.id, "hypothesis_critique",
            {"cycle_public_id": cycle.public_id},
        )
        target = CycleStatus.QUEUED
    elif command == "request_protocol_compilation":
        if current != CycleStatus.READY:
            raise HTTPException(status_code=400, detail="Cycle must be READY")
        from libs.orchestration.job_queue import enqueue_job as _enqueue_job
        _enqueue_job(
            session, actor, cycle.id, "protocol_compilation",
            {"cycle_public_id": cycle.public_id},
        )
        target = CycleStatus.QUEUED
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


def get_run_by_public_id(session: Session, run_public_id: str) -> RunRecordModel:
    run = session.scalar(select(RunRecordModel).where(RunRecordModel.public_id == run_public_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _build_run_record_response(
    session: Session,
    run: RunRecordModel,
) -> RunRecord:
    cycle = session.get(ResearchCycleModel, run.cycle_id)
    spec = session.get(ExperimentSpecModel, run.experiment_spec_id)
    cycle_public_id = cycle.public_id if cycle else ""
    spec_public_id = spec.public_id if spec else ""
    return RunRecord(
        public_id=run.public_id,
        cycle_public_id=cycle_public_id,
        experiment_spec_public_id=spec_public_id,
        status=run.status,
        execution_profile=run.execution_profile,
        run_spec=RunSpec(
            workspace_path=run.workspace_path,
            image=run.image,
            build_recipe=run.build_recipe or {},
            command=run.command or [],
            env_vars=run.env_vars or {},
            mounts=run.mounts or [],
            hardware_profile=run.hardware_profile,
            timeout_seconds=run.timeout_seconds,
            memory_limit_mb=run.memory_limit_mb,
            cpu_limit=run.cpu_limit,
            gpu_enabled=run.gpu_enabled,
            network_mode=run.network_mode,
            artifact_output_path=run.artifact_root,
            patch_archive_path=run.patch_archive_path,
        ),
        workspace_path=run.workspace_path,
        artifact_root=run.artifact_root,
        stdout_path=run.stdout_path,
        stderr_path=run.stderr_path,
        patch_archive_path=run.patch_archive_path,
        base_commit=run.base_commit,
        base_branch=run.base_branch,
        bound_skill_keys=run.bound_skill_keys or [],
        prompt_lineage=run.prompt_lineage or [],
        model_lineage=run.model_lineage or [],
        latest_resource_snapshot=run.latest_resource_snapshot or {},
        metrics_summary=run.metrics_summary or {},
        artifact_manifest=run.artifact_manifest or {},
        failure_classification=run.failure_classification,
        verification_outcome=run.verification_outcome,
        last_error=run.last_error,
        exit_code=run.exit_code,
        attempt_count=run.attempt_count,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def create_run_from_experiment_spec(
    session: Session,
    actor: Actor,
    config: AppConfig,
    experiment_spec_public_id: str,
    payload: RunCreateRequest,
) -> RunRecordModel:
    spec_query = select(ExperimentSpecModel).where(
        ExperimentSpecModel.public_id == experiment_spec_public_id
    )
    spec = session.scalar(spec_query)
    if spec is None:
        raise HTTPException(status_code=404, detail="Experiment spec not found")
    if spec.status not in {"valid", "approved"}:
        raise HTTPException(status_code=400, detail="Experiment spec must be valid or approved")

    cycle = session.get(ResearchCycleModel, spec.cycle_id)
    if cycle is None:
        raise HTTPException(status_code=400, detail="Experiment spec is missing its cycle")

    run_public_id = generate_public_id("run")
    profile = load_execution_profile(config, payload.execution_profile)
    image_key = profile["image_key"]
    network_mode = profile.get("network_mode", "disabled")
    decision = evaluate_run_policy(
        config,
        execution_profile=payload.execution_profile,
        network_mode=str(network_mode),
        image_key=str(image_key),
        force_start=payload.force_start,
    )
    paths = determine_run_paths(config, run_public_id)
    spec_schema = get_experiment_spec_detail_api(session, cycle.public_id, spec.public_id)
    run_spec = build_run_spec(
        config=config,
        run_public_id=run_public_id,
        workspace_path=config.workspaces_dir / run_public_id,
        experiment_spec=spec_schema,
        execution_profile=payload.execution_profile,
        patch_archive_path=paths.patch_archive_path,
        artifact_root=paths.artifact_root,
        env_overrides=payload.env_overrides,
    )
    status = "queued" if decision.allowed else "policy_blocked"
    run = RunRecordModel(
        public_id=run_public_id,
        cycle_id=cycle.id,
        experiment_spec_id=spec.id,
        status=status,
        execution_profile=payload.execution_profile,
        workspace_path=run_spec.workspace_path,
        artifact_root=run_spec.artifact_output_path,
        stdout_path=str(paths.stdout_path),
        stderr_path=str(paths.stderr_path),
        patch_archive_path=run_spec.patch_archive_path,
        base_commit=None,
        base_branch=None,
        image=run_spec.image,
        build_recipe=run_spec.build_recipe,
        command=run_spec.command,
        env_vars=run_spec.env_vars,
        mounts=run_spec.mounts,
        hardware_profile=run_spec.hardware_profile,
        timeout_seconds=run_spec.timeout_seconds,
        memory_limit_mb=run_spec.memory_limit_mb,
        cpu_limit=run_spec.cpu_limit,
        gpu_enabled=run_spec.gpu_enabled,
        network_mode=run_spec.network_mode,
        bound_skill_keys=[],
        prompt_lineage=[],
        model_lineage=[],
        latest_resource_snapshot={},
        metrics_summary={},
        artifact_manifest={},
        failure_classification="policy_rejection" if not decision.allowed else None,
        last_error=decision.reason if not decision.allowed else None,
        last_completed_operator=None,
        last_completed_job_id=None,
        resume_payload={},
        attempt_count=0,
    )
    session.add(run)
    session.flush()

    event_type = "run_created" if decision.allowed else "run_policy_blocked"
    append_event(
        session,
        actor=actor,
        event_type=event_type,
        payload={
            "cycle_public_id": cycle.public_id,
            "run_public_id": run.public_id,
            "experiment_spec_public_id": spec.public_id,
            "status": run.status,
            "reason": decision.reason,
        },
        cycle_id=cycle.id,
        scope_used=TokenScope.RUNS_CONTROL.value,
    )

    if decision.allowed:
        from libs.orchestration.job_queue import enqueue_job as _enqueue_job

        _enqueue_job(
            session,
            actor,
            cycle.id,
            "run_prepare",
            {"cycle_public_id": cycle.public_id, "run_public_id": run.public_id},
        )
        create_state_snapshot(
            session,
            cycle=cycle,
            target_state=CycleStatus.QUEUED,
            actor=actor,
            reason="Execution run queued",
            context={"run_public_id": run.public_id},
            scope_used=TokenScope.RUNS_CONTROL.value,
        )
    return run


def list_runs_for_cycle_api(session: Session, cycle_public_id: str) -> RunListResponse:
    cycle = get_cycle_by_public_id(session, cycle_public_id)
    runs = session.scalars(
        select(RunRecordModel)
        .where(RunRecordModel.cycle_id == cycle.id)
        .order_by(RunRecordModel.created_at.desc())
    ).all()
    spec_ids = {run.experiment_spec_id for run in runs}
    specs = {}
    if spec_ids:
        spec_query = select(ExperimentSpecModel).where(ExperimentSpecModel.id.in_(spec_ids))
        for spec in session.scalars(spec_query).all():
            specs[spec.id] = spec.public_id
    items = [
        RunSummary(
            public_id=run.public_id,
            experiment_spec_public_id=specs.get(run.experiment_spec_id, ""),
            status=run.status,
            execution_profile=run.execution_profile,
            failure_classification=run.failure_classification,
            verification_outcome=run.verification_outcome,
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
        )
        for run in runs
    ]
    return RunListResponse(items=items, total=len(items))


def list_run_telemetry_after(
    session: Session,
    run_public_id: str,
    last_event_id: int,
) -> list[RunTelemetryEvent]:
    run = get_run_by_public_id(session, run_public_id)
    events = session.scalars(
        select(RunTelemetryEventModel)
        .where(
            RunTelemetryEventModel.run_record_id == run.id,
            RunTelemetryEventModel.sequence_id > last_event_id,
        )
        .order_by(RunTelemetryEventModel.sequence_id.asc())
        .limit(200)
    ).all()
    return [
        RunTelemetryEvent(
            sequence_id=event.sequence_id,
            public_id=event.public_id,
            run_public_id=run.public_id,
            event_type=event.event_type,
            stream=event.stream,
            message=event.message,
            payload=event.payload or {},
            created_at=event.created_at,
        )
        for event in events
    ]


def append_run_telemetry_event(
    session: Session,
    *,
    run: RunRecordModel,
    event_type: str,
    payload: dict[str, Any] | None = None,
    stream: str | None = None,
    message: str | None = None,
) -> RunTelemetryEventModel:
    event = RunTelemetryEventModel(
        public_id=generate_public_id("rtevt"),
        run_record_id=run.id,
        event_type=event_type,
        stream=stream,
        message=message,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event


def get_run_detail_api(session: Session, run_public_id: str) -> RunDetailResponse:
    run = get_run_by_public_id(session, run_public_id)
    telemetry = list_run_telemetry_after(session, run_public_id, 0)
    cycle = session.get(ResearchCycleModel, run.cycle_id)
    skill_records = session.scalars(
        select(SkillExecutionRecordModel)
        .where(SkillExecutionRecordModel.run_record_id == run.id)
        .order_by(SkillExecutionRecordModel.created_at.desc())
    ).all()
    reports = session.scalars(
        select(ReportBundleModel)
        .where(ReportBundleModel.cycle_id == run.cycle_id)
        .order_by(ReportBundleModel.created_at.desc())
    ).all()
    run_reports = [
        ReportSummary(
            public_id=report.public_id,
            cycle_public_id=cycle.public_id if cycle else None,
            report_type=report.report_type,
            title=report.title,
            artifact_path=report.artifact_path,
            created_at=report.created_at,
        )
        for report in reports
        if (report.report_metadata or {}).get("run_public_id") == run.public_id
    ]
    artifact_manifest = None
    if run.artifact_manifest:
        artifact_manifest = RunArtifactManifest(
            run_public_id=run.public_id,
            manifest_path=str(run.artifact_manifest.get("manifest_path", "")),
            metrics_path=run.artifact_manifest.get("metrics_path"),
            checkpoint_path=run.artifact_manifest.get("checkpoint_path"),
            predictions_path=run.artifact_manifest.get("predictions_path"),
            artifacts=run.artifact_manifest.get("artifacts", []),
        )
    # Phase 4 — verification and postmortem
    vr = session.scalar(
        select(VerificationReportModel).where(
            VerificationReportModel.run_record_id == run.id
        )
    )
    vr_summary = None
    if vr is not None:
        spec_obj = session.get(ExperimentSpecModel, vr.experiment_spec_id)
        vr_summary = VerificationReportSummary(
            public_id=vr.public_id,
            run_public_id=run.public_id,
            experiment_spec_public_id=spec_obj.public_id if spec_obj else "",
            outcome=vr.outcome,
            reviewer_summary=vr.reviewer_summary,
            created_at=vr.created_at,
        )
    pm = session.scalar(
        select(FailurePostmortemModel).where(
            FailurePostmortemModel.run_record_id == run.id
        )
    )
    pm_summary = None
    if pm is not None:
        pm_summary = FailurePostmortemSummary(
            public_id=pm.public_id,
            run_public_id=run.public_id,
            failure_class=pm.failure_class,
            failure_stage=pm.failure_stage,
            root_cause_summary=pm.root_cause_summary,
            created_at=pm.created_at,
        )

    return RunDetailResponse(
        run=_build_run_record_response(session, run),
        artifact_manifest=artifact_manifest,
        telemetry_events=telemetry,
        skill_execution_records=[
            SkillExecutionRecord(
                public_id=item.public_id,
                operator_name=item.operator_name,
                status=item.status,
                run_public_id=run.public_id,
                payload=item.payload,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in skill_records
        ],
        reports=run_reports,
        verification_report=vr_summary,
        postmortem=pm_summary,
    )


def apply_run_command(
    session: Session,
    actor: Actor,
    run_public_id: str,
    command: str,
) -> RunRecordModel:
    run = get_run_by_public_id(session, run_public_id)
    cycle = session.get(ResearchCycleModel, run.cycle_id)
    if cycle is None:
        raise HTTPException(status_code=400, detail="Run is missing its cycle")

    if command == "pause":
        if run.status not in {"running", "ready_to_execute"}:
            raise HTTPException(status_code=400, detail="Run is not pausable")
        run.status = "pause_requested" if run.status == "running" else "paused"
    elif command == "cancel":
        if run.status not in {"queued", "preparing", "ready_to_execute", "running", "paused"}:
            raise HTTPException(status_code=400, detail="Run is not cancellable")
        run.status = "cancel_requested" if run.status == "running" else "cancelled"
    elif command == "retry":
        if run.status not in {"failed", "paused"}:
            raise HTTPException(status_code=400, detail="Run is not retryable")
        from libs.core.config import get_config as _get_config
        from libs.orchestration.job_queue import enqueue_job as _enqueue_job

        policy = _get_config().policy
        if run.attempt_count >= policy.max_retry_attempts:
            raise HTTPException(
                status_code=400,
                detail=f"Run has reached maximum retry attempts ({policy.max_retry_attempts})",
            )

        repairable = {
            "build_failure",
            "dependency_failure",
            "runtime_exception",
            "harness_mismatch",
            "skill_contract_violation",
        }
        next_operator = (
            "run_retry_repair"
            if run.failure_classification in repairable
            else "run_execute"
        )
        _enqueue_job(
            session,
            actor,
            cycle.id,
            next_operator,
            {"cycle_public_id": cycle.public_id, "run_public_id": run.public_id},
        )
        run.status = "queued"
        create_state_snapshot(
            session,
            cycle=cycle,
            target_state=CycleStatus.QUEUED,
            actor=actor,
            reason=f"Run command applied: {command}",
            context={"run_public_id": run.public_id},
            scope_used=TokenScope.RUNS_CONTROL.value,
        )
    elif command == "resume":
        if run.status not in {"failed", "paused"}:
            raise HTTPException(status_code=400, detail="Run is not resumable")
        from libs.core.config import get_config as _get_config
        from libs.orchestration.job_queue import enqueue_job as _enqueue_job
        from libs.orchestration.worker import next_operator_after

        policy = _get_config().policy
        if run.attempt_count >= policy.max_retry_attempts:
            raise HTTPException(
                status_code=400,
                detail=f"Run has reached maximum retry attempts ({policy.max_retry_attempts})",
            )
        # Determine where to resume from: use the run-specific checkpoint.
        last_op = run.last_completed_operator
        next_op = next_operator_after(last_op) if last_op else "run_prepare"
        if next_op is None:
            next_op = "run_prepare"
        run.resume_payload = {
            "resume_from": last_op,
            "next_operator": next_op,
            "requested_at": datetime.now(UTC).isoformat(),
        }
        _enqueue_job(
            session,
            actor,
            cycle.id,
            next_op,
            {"cycle_public_id": cycle.public_id, "run_public_id": run.public_id},
        )
        run.status = "queued"
        create_state_snapshot(
            session,
            cycle=cycle,
            target_state=CycleStatus.RESUMING,
            actor=actor,
            reason=f"Resuming from checkpoint: {last_op or 'start'}",
            context={
                "run_public_id": run.public_id,
                "resume_from": last_op,
                "next_operator": next_op,
            },
            scope_used=TokenScope.RUNS_CONTROL.value,
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported run command")

    append_event(
        session,
        actor=actor,
        event_type="run_command_received",
        payload={"run_public_id": run.public_id, "command": command, "status": run.status},
        cycle_id=cycle.id,
        scope_used=TokenScope.RUNS_CONTROL.value,
    )
    return run


def _has_pending_jobs(session: Session, cycle_id: int) -> bool:
    job = session.scalar(
        select(JobModel).where(
            JobModel.cycle_id == cycle_id,
            JobModel.status.in_(["pending", "claimed"]),
        )
    )
    return job is not None


# ---------------------------------------------------------------------------
# Phase 1 — Literature query helpers
# ---------------------------------------------------------------------------


def list_papers_for_cycle(
    session: Session, cycle_public_id: str, status_filter: str | None = None,
) -> list[PaperCardSummary]:
    from libs.literature.services import retrieval_provenance_summary
    from libs.storage.models import PaperCardModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    query = (
        select(PaperCardModel)
        .where(PaperCardModel.cycle_id == cycle.id)
    )
    if status_filter:
        query = query.where(PaperCardModel.lifecycle_status == status_filter)
    query = query.order_by(
        PaperCardModel.shortlist_rank.asc().nullslast(),
        PaperCardModel.triage_score.desc().nullslast(),
        PaperCardModel.created_at.asc(),
    ).limit(200)
    papers = session.scalars(query).all()
    return [
        PaperCardSummary(
            public_id=p.public_id,
            title=p.title,
            source_type=p.source_type,
            external_id=p.external_id,
            lifecycle_status=p.lifecycle_status,
            triage_score=p.triage_score,
            triage_rationale=p.triage_rationale,
            shortlist_rank=p.shortlist_rank,
            shortlist_reason=p.shortlist_reason,
            escalation_reason=p.escalation_reason,
            escalation_type=p.escalation_type,
            retrieval_provenance_summary=retrieval_provenance_summary(p.metadata_extra or {}),
            created_at=p.created_at,
        )
        for p in papers
    ]


def get_paper_detail(
    session: Session, cycle_public_id: str, paper_public_id: str,
) -> PaperCardDetail:
    from libs.literature.services import retrieval_provenance_summary
    from libs.schemas.domain import PaperCard as PaperCardSchema
    from libs.schemas.domain import ScreeningDecision
    from libs.storage.models import PaperCardModel, ScreeningDecisionModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    paper = session.scalar(
        select(PaperCardModel).where(
            PaperCardModel.public_id == paper_public_id,
            PaperCardModel.cycle_id == cycle.id,
        )
    )
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    decisions = session.scalars(
        select(ScreeningDecisionModel)
        .where(ScreeningDecisionModel.paper_card_id == paper.id)
        .order_by(ScreeningDecisionModel.created_at.desc())
    ).all()

    return PaperCardDetail(
        **PaperCardSchema.model_validate(paper).model_dump(),
        screening_decisions=[ScreeningDecision.model_validate(d) for d in decisions],
        retrieval_provenance_summary=retrieval_provenance_summary(paper.metadata_extra or {}),
    )


def get_literature_summary(
    session: Session, cycle_public_id: str,
) -> LiteratureTriageResponse:
    from libs.literature.services import build_literature_triage_summary

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    return build_literature_triage_summary(session, cycle)


def list_retrieval_sessions_for_cycle(
    session: Session, cycle_public_id: str,
) -> list:
    from libs.schemas.domain import SourceRetrievalSession as SRSDomain
    from libs.storage.models import SourceRetrievalSessionModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    sessions = session.scalars(
        select(SourceRetrievalSessionModel)
        .where(SourceRetrievalSessionModel.cycle_id == cycle.id)
        .order_by(SourceRetrievalSessionModel.created_at.asc())
    ).all()
    return [SRSDomain.model_validate(s) for s in sessions]


# ---------------------------------------------------------------------------
# Phase 2 — Evidence, Hypotheses, Experiment Specs query helpers
# ---------------------------------------------------------------------------


def list_evidence_for_cycle_api(
    session: Session, cycle_public_id: str, type_filter: str | None = None,
) -> EvidenceListResponse:
    from libs.storage.models import EvidenceCardModel, PaperCardModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    stmt = (
        select(EvidenceCardModel)
        .where(EvidenceCardModel.cycle_id == cycle.id)
    )
    if type_filter:
        stmt = stmt.where(EvidenceCardModel.evidence_type == type_filter)
    stmt = stmt.order_by(EvidenceCardModel.relevance_score.desc()).limit(200)
    cards = session.scalars(stmt).all()

    paper_ids = {c.paper_card_id for c in cards}
    papers = {
        p.id: p.public_id
        for p in session.scalars(
            select(PaperCardModel).where(PaperCardModel.id.in_(paper_ids))
        ).all()
    } if paper_ids else {}

    items = [
        EvidenceCardSummary(
            public_id=c.public_id,
            paper_public_id=papers.get(c.paper_card_id, ""),
            claim=c.claim,
            evidence_type=c.evidence_type,
            strength=c.strength,
            relevance_score=c.relevance_score,
            read_depth=c.read_depth,
            created_at=c.created_at,
        )
        for c in cards
    ]
    return EvidenceListResponse(items=items, total=len(items))


def get_evidence_detail_api(
    session: Session, cycle_public_id: str, evidence_public_id: str,
) -> EvidenceCardDetail:
    from libs.schemas.domain import EvidenceCard as EvidenceCardSchema
    from libs.storage.models import EvidenceCardModel, PaperCardModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    card = session.scalar(
        select(EvidenceCardModel).where(
            EvidenceCardModel.public_id == evidence_public_id,
            EvidenceCardModel.cycle_id == cycle.id,
        )
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Evidence card not found")

    paper = session.get(PaperCardModel, card.paper_card_id)
    paper_pub_id = paper.public_id if paper else ""

    schema = EvidenceCardSchema(
        public_id=card.public_id,
        paper_public_id=paper_pub_id,
        claim=card.claim,
        evidence_type=card.evidence_type,
        strength=card.strength,
        relevance_score=card.relevance_score,
        relevance_rationale=card.relevance_rationale,
        source_section=card.source_section,
        source_quote=card.source_quote,
        read_depth=card.read_depth,
        conflict_with=card.conflict_with or [],
        redundant_with=card.redundant_with or [],
        conflict_notes=card.conflict_notes,
        model_route_id=card.model_route_id,
        prompt_id=card.prompt_id,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )
    return EvidenceCardDetail(**schema.model_dump())


def get_evidence_summary_api(
    session: Session, cycle_public_id: str,
) -> EvidenceSummaryResponse:
    from libs.ideation.services import build_evidence_summary

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    summary = build_evidence_summary(session, cycle.id)
    return EvidenceSummaryResponse(**summary)


def list_hypotheses_for_cycle_api(
    session: Session, cycle_public_id: str,
) -> HypothesisListResponse:
    from libs.storage.models import HypothesisCardModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    cards = session.scalars(
        select(HypothesisCardModel)
        .where(HypothesisCardModel.cycle_id == cycle.id)
        .order_by(
            HypothesisCardModel.portfolio_rank.asc().nullslast(),
            HypothesisCardModel.created_at.asc(),
        )
        .limit(100)
    ).all()

    items = [
        HypothesisCardSummary(
            public_id=c.public_id,
            title=c.title,
            portfolio_rank=c.portfolio_rank,
            portfolio_score=c.portfolio_score,
            status=c.status,
            novelty_score=c.novelty_score,
            feasibility_score=c.feasibility_score,
            impact_score=c.impact_score,
            created_at=c.created_at,
        )
        for c in cards
    ]
    return HypothesisListResponse(items=items, total=len(items))


def get_hypothesis_detail_api(
    session: Session, cycle_public_id: str, hypothesis_public_id: str,
) -> HypothesisCardDetail:
    from libs.schemas.domain import HypothesisCard as HypothesisCardSchema
    from libs.storage.models import EvidenceCardModel, HypothesisCardModel, PaperCardModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    hyp = session.scalar(
        select(HypothesisCardModel).where(
            HypothesisCardModel.public_id == hypothesis_public_id,
            HypothesisCardModel.cycle_id == cycle.id,
        )
    )
    if hyp is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    all_evidence_ids = list(set((hyp.supporting_evidence or []) + (hyp.counter_evidence or [])))
    evidence_cards_list: list[EvidenceCardSummary] = []
    if all_evidence_ids:
        ev_models = session.scalars(
            select(EvidenceCardModel).where(
                EvidenceCardModel.public_id.in_(all_evidence_ids),
            )
        ).all()
        paper_ids = {e.paper_card_id for e in ev_models}
        papers = {
            p.id: p.public_id
            for p in session.scalars(
                select(PaperCardModel).where(PaperCardModel.id.in_(paper_ids))
            ).all()
        } if paper_ids else {}
        evidence_cards_list = [
            EvidenceCardSummary(
                public_id=e.public_id,
                paper_public_id=papers.get(e.paper_card_id, ""),
                claim=e.claim,
                evidence_type=e.evidence_type,
                strength=e.strength,
                relevance_score=e.relevance_score,
                read_depth=e.read_depth,
                created_at=e.created_at,
            )
            for e in ev_models
        ]

    schema = HypothesisCardSchema.model_validate(hyp)
    return HypothesisCardDetail(**schema.model_dump(), evidence_cards=evidence_cards_list)


def get_portfolio_ranking_api(
    session: Session, cycle_public_id: str,
) -> PortfolioRankingResponse:
    from libs.storage.models import HypothesisCardModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    ranked = session.scalars(
        select(HypothesisCardModel).where(
            HypothesisCardModel.cycle_id == cycle.id,
            HypothesisCardModel.portfolio_rank.isnot(None),
        ).order_by(HypothesisCardModel.portfolio_rank.asc())
    ).all()

    items = [
        HypothesisCardSummary(
            public_id=c.public_id,
            title=c.title,
            portfolio_rank=c.portfolio_rank,
            portfolio_score=c.portfolio_score,
            status=c.status,
            novelty_score=c.novelty_score,
            feasibility_score=c.feasibility_score,
            impact_score=c.impact_score,
            created_at=c.created_at,
        )
        for c in ranked
    ]
    return PortfolioRankingResponse(
        cycle_public_id=cycle.public_id,
        hypotheses=items,
        ranking_method="composite_score",
        total=len(items),
    )


def list_experiment_specs_for_cycle_api(
    session: Session, cycle_public_id: str,
) -> ExperimentSpecListResponse:
    from libs.storage.models import ExperimentSpecModel, HypothesisCardModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    specs = session.scalars(
        select(ExperimentSpecModel)
        .where(ExperimentSpecModel.cycle_id == cycle.id)
        .order_by(ExperimentSpecModel.created_at.asc())
    ).all()

    hyp_ids = {s.hypothesis_card_id for s in specs}
    hyps = {
        h.id: h.public_id
        for h in session.scalars(
            select(HypothesisCardModel).where(HypothesisCardModel.id.in_(hyp_ids))
        ).all()
    } if hyp_ids else {}

    items = [
        ExperimentSpecSummary(
            public_id=s.public_id,
            hypothesis_public_id=hyps.get(s.hypothesis_card_id, ""),
            title=s.title,
            status=s.status,
            gpu_required=s.gpu_required,
            estimated_runtime_minutes=s.estimated_runtime_minutes,
            created_at=s.created_at,
        )
        for s in specs
    ]
    return ExperimentSpecListResponse(items=items, total=len(items))


def get_experiment_spec_detail_api(
    session: Session, cycle_public_id: str, spec_public_id: str,
) -> ExperimentSpecDetail:
    from libs.schemas.domain import ExperimentSpec as ExperimentSpecSchema
    from libs.storage.models import ExperimentSpecModel, HypothesisCardModel

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    spec = session.scalar(
        select(ExperimentSpecModel).where(
            ExperimentSpecModel.public_id == spec_public_id,
            ExperimentSpecModel.cycle_id == cycle.id,
        )
    )
    if spec is None:
        raise HTTPException(status_code=404, detail="Experiment spec not found")

    hyp = session.get(HypothesisCardModel, spec.hypothesis_card_id)
    hyp_pub_id = hyp.public_id if hyp else ""

    hyp_summary = None
    if hyp:
        hyp_summary = HypothesisCardSummary(
            public_id=hyp.public_id,
            title=hyp.title,
            portfolio_rank=hyp.portfolio_rank,
            portfolio_score=hyp.portfolio_score,
            status=hyp.status,
            novelty_score=hyp.novelty_score,
            feasibility_score=hyp.feasibility_score,
            impact_score=hyp.impact_score,
            created_at=hyp.created_at,
        )

    schema = ExperimentSpecSchema(
        public_id=spec.public_id,
        hypothesis_public_id=hyp_pub_id,
        title=spec.title,
        objective=spec.objective,
        baseline_description=spec.baseline_description,
        method_description=spec.method_description,
        controls=spec.controls or [],
        metrics=spec.metrics or [],
        datasets=spec.datasets or [],
        artifacts=spec.artifacts or [],
        stop_conditions=spec.stop_conditions or [],
        expected_outputs=spec.expected_outputs or [],
        status=spec.status,
        validation_issues=spec.validation_issues or [],
        rejection_reason=spec.rejection_reason,
        estimated_runtime_minutes=spec.estimated_runtime_minutes,
        gpu_required=spec.gpu_required,
        resource_requirements=spec.resource_requirements or {},
        model_route_id=spec.model_route_id,
        prompt_id=spec.prompt_id,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
    )
    return ExperimentSpecDetail(**schema.model_dump(), hypothesis=hyp_summary)


# ---------------------------------------------------------------------------
# Phase 4 — Verification & Postmortems
# ---------------------------------------------------------------------------


def create_verification_report(
    session: Session,
    *,
    cycle: ResearchCycleModel,
    run: RunRecordModel,
    experiment_spec: ExperimentSpecModel,
    hypothesis_card_id: int | None,
    outcome: str,
    outcome_rationale: str,
    baseline_comparison: dict[str, Any],
    historical_comparisons: list[dict[str, Any]],
    metric_sanity_checks: list[dict[str, Any]],
    artifact_checks: list[dict[str, Any]],
    leakage_signals: list[dict[str, Any]],
    output_contract_checks: list[dict[str, Any]],
    split_validation: dict[str, Any],
    rerun_note: str | None,
    reviewer_summary: str,
    model_route_id: str,
    prompt_id: str,
) -> VerificationReportModel:
    record = VerificationReportModel(
        public_id=generate_public_id("vr"),
        cycle_id=cycle.id,
        run_record_id=run.id,
        experiment_spec_id=experiment_spec.id,
        hypothesis_card_id=hypothesis_card_id,
        outcome=outcome,
        outcome_rationale=outcome_rationale,
        baseline_comparison=baseline_comparison,
        historical_comparisons=historical_comparisons,
        metric_sanity_checks=metric_sanity_checks,
        artifact_checks=artifact_checks,
        output_contract_checks=output_contract_checks,
        leakage_signals=leakage_signals,
        split_validation=split_validation,
        rerun_note=rerun_note,
        reviewer_summary=reviewer_summary,
        model_route_id=model_route_id,
        prompt_id=prompt_id,
    )
    session.add(record)
    session.flush()
    return record


def create_failure_postmortem(
    session: Session,
    *,
    cycle: ResearchCycleModel,
    run: RunRecordModel,
    verification_report_id: int | None,
    failure_class: str,
    failure_stage: str,
    root_cause_summary: str,
    contributing_factors: list[dict[str, Any]],
    remediation_suggestions: list[dict[str, Any]],
    retrieval_hints: list[dict[str, Any]],
    protocol_update_hints: list[dict[str, Any]],
    similar_prior_failures: list[dict[str, Any]],
    model_route_id: str,
    prompt_id: str,
) -> FailurePostmortemModel:
    record = FailurePostmortemModel(
        public_id=generate_public_id("pm"),
        cycle_id=cycle.id,
        run_record_id=run.id,
        verification_report_id=verification_report_id,
        failure_class=failure_class,
        failure_stage=failure_stage,
        root_cause_summary=root_cause_summary,
        contributing_factors=contributing_factors,
        remediation_suggestions=remediation_suggestions,
        retrieval_hints=retrieval_hints,
        protocol_update_hints=protocol_update_hints,
        similar_prior_failures=similar_prior_failures,
        model_route_id=model_route_id,
        prompt_id=prompt_id,
    )
    session.add(record)
    session.flush()
    return record


def get_verification_report_for_run(
    session: Session, run_public_id: str,
) -> VerificationReportModel | None:
    run = get_run_by_public_id(session, run_public_id)
    return session.scalar(
        select(VerificationReportModel).where(
            VerificationReportModel.run_record_id == run.id
        )
    )


def get_postmortem_for_run(
    session: Session, run_public_id: str,
) -> FailurePostmortemModel | None:
    run = get_run_by_public_id(session, run_public_id)
    return session.scalar(
        select(FailurePostmortemModel).where(
            FailurePostmortemModel.run_record_id == run.id
        )
    )


def list_verification_reports_for_cycle(
    session: Session, cycle_public_id: str,
) -> VerificationReportListResponse:
    cycle = get_cycle_by_public_id(session, cycle_public_id)
    reports = session.scalars(
        select(VerificationReportModel)
        .where(VerificationReportModel.cycle_id == cycle.id)
        .order_by(VerificationReportModel.created_at.desc())
    ).all()
    items = []
    for vr in reports:
        run = session.get(RunRecordModel, vr.run_record_id)
        spec = session.get(ExperimentSpecModel, vr.experiment_spec_id)
        items.append(
            VerificationReportSummary(
                public_id=vr.public_id,
                run_public_id=run.public_id if run else "",
                experiment_spec_public_id=spec.public_id if spec else "",
                outcome=vr.outcome,
                reviewer_summary=vr.reviewer_summary,
                created_at=vr.created_at,
            )
        )
    return VerificationReportListResponse(items=items, total=len(items))


def list_postmortems_for_cycle(
    session: Session, cycle_public_id: str,
) -> FailurePostmortemListResponse:
    cycle = get_cycle_by_public_id(session, cycle_public_id)
    postmortems = session.scalars(
        select(FailurePostmortemModel)
        .where(FailurePostmortemModel.cycle_id == cycle.id)
        .order_by(FailurePostmortemModel.created_at.desc())
    ).all()
    items = []
    for pm in postmortems:
        run = session.get(RunRecordModel, pm.run_record_id)
        items.append(
            FailurePostmortemSummary(
                public_id=pm.public_id,
                run_public_id=run.public_id if run else "",
                failure_class=pm.failure_class,
                failure_stage=pm.failure_stage,
                root_cause_summary=pm.root_cause_summary,
                created_at=pm.created_at,
            )
        )
    return FailurePostmortemListResponse(items=items, total=len(items))


def _build_verification_report_detail(
    session: Session, vr: VerificationReportModel,
) -> VerificationReportDetail:
    run = session.get(RunRecordModel, vr.run_record_id)
    spec = session.get(ExperimentSpecModel, vr.experiment_spec_id)
    cycle = session.get(ResearchCycleModel, vr.cycle_id)
    hyp_pub_id = None
    if vr.hypothesis_card_id:
        from libs.storage.models import HypothesisCardModel

        hyp = session.get(HypothesisCardModel, vr.hypothesis_card_id)
        hyp_pub_id = hyp.public_id if hyp else None
    return VerificationReportDetail(
        public_id=vr.public_id,
        cycle_public_id=cycle.public_id if cycle else "",
        run_public_id=run.public_id if run else "",
        experiment_spec_public_id=spec.public_id if spec else "",
        hypothesis_public_id=hyp_pub_id,
        outcome=vr.outcome,
        outcome_rationale=vr.outcome_rationale,
        baseline_comparison=vr.baseline_comparison or {},
        historical_comparisons=vr.historical_comparisons or [],
        metric_sanity_checks=vr.metric_sanity_checks or [],
        artifact_checks=vr.artifact_checks or [],
        output_contract_checks=vr.output_contract_checks or [],
        leakage_signals=vr.leakage_signals or [],
        split_validation=vr.split_validation or {},
        rerun_note=vr.rerun_note,
        reviewer_summary=vr.reviewer_summary,
        model_route_id=vr.model_route_id,
        prompt_id=vr.prompt_id,
        created_at=vr.created_at,
        updated_at=vr.updated_at,
    )


def get_verification_report_detail(
    session: Session, report_public_id: str,
) -> VerificationReportDetail:
    vr = session.scalar(
        select(VerificationReportModel).where(
            VerificationReportModel.public_id == report_public_id
        )
    )
    if vr is None:
        raise HTTPException(status_code=404, detail="Verification report not found")
    return _build_verification_report_detail(session, vr)


def get_postmortem_detail(
    session: Session, postmortem_public_id: str,
) -> FailurePostmortemDetail:
    pm = session.scalar(
        select(FailurePostmortemModel).where(
            FailurePostmortemModel.public_id == postmortem_public_id
        )
    )
    if pm is None:
        raise HTTPException(status_code=404, detail="Postmortem not found")
    run = session.get(RunRecordModel, pm.run_record_id)
    cycle = session.get(ResearchCycleModel, pm.cycle_id)
    vr_pub_id = None
    if pm.verification_report_id:
        vr = session.get(VerificationReportModel, pm.verification_report_id)
        vr_pub_id = vr.public_id if vr else None
    return FailurePostmortemDetail(
        public_id=pm.public_id,
        cycle_public_id=cycle.public_id if cycle else "",
        run_public_id=run.public_id if run else "",
        verification_report_public_id=vr_pub_id,
        failure_class=pm.failure_class,
        failure_stage=pm.failure_stage,
        root_cause_summary=pm.root_cause_summary,
        contributing_factors=pm.contributing_factors or [],
        remediation_suggestions=pm.remediation_suggestions or [],
        retrieval_hints=pm.retrieval_hints or [],
        protocol_update_hints=pm.protocol_update_hints or [],
        similar_prior_failures=pm.similar_prior_failures or [],
        model_route_id=pm.model_route_id,
        prompt_id=pm.prompt_id,
        created_at=pm.created_at,
        updated_at=pm.updated_at,
    )


def get_verification_summary_for_cycle(
    session: Session, cycle_public_id: str,
) -> VerificationSummaryResponse:
    from libs.core.config import get_config

    cycle = get_cycle_by_public_id(session, cycle_public_id)
    runs = session.scalars(
        select(RunRecordModel).where(RunRecordModel.cycle_id == cycle.id)
    ).all()
    total = len(runs)
    robust = sum(1 for r in runs if r.verification_outcome == "robust")
    tentative = sum(1 for r in runs if r.verification_outcome == "tentative")
    rejected = sum(1 for r in runs if r.verification_outcome == "rejected")
    invalid = sum(1 for r in runs if r.verification_outcome == "invalid")
    pending = sum(1 for r in runs if r.verification_outcome is None)
    pm_count = session.scalar(
        select(sa_func.count())
        .select_from(FailurePostmortemModel)
        .where(FailurePostmortemModel.cycle_id == cycle.id)
    ) or 0
    latest_verification_report = session.scalar(
        select(VerificationReportModel)
        .where(VerificationReportModel.cycle_id == cycle.id)
        .order_by(VerificationReportModel.created_at.desc())
    )
    latest_postmortem = session.scalar(
        select(FailurePostmortemModel)
        .where(FailurePostmortemModel.cycle_id == cycle.id)
        .order_by(FailurePostmortemModel.created_at.desc())
    )
    latest_cycle_summary_report = session.scalar(
        select(ReportBundleModel)
        .where(
            ReportBundleModel.cycle_id == cycle.id,
            ReportBundleModel.report_type == "verification_cycle_summary",
        )
        .order_by(ReportBundleModel.created_at.desc())
    )
    verification_policy = get_config().load_yaml(get_config().policy_config_path).get(
        "verification", {}
    )
    recommendations = build_next_step_recommendations(
        outcome=latest_verification_report.outcome if latest_verification_report else "tentative",
        min_outcome_for_promotion=str(
            verification_policy.get("min_outcome_for_promotion", "tentative")
        ),
        rerun_note=latest_verification_report.rerun_note if latest_verification_report else None,
        retrieval_hints=latest_postmortem.retrieval_hints if latest_postmortem else [],
        protocol_update_hints=(
            latest_postmortem.protocol_update_hints if latest_postmortem else []
        ),
        reviewer_summary=(
            latest_verification_report.reviewer_summary if latest_verification_report else None
        ),
    )
    return VerificationSummaryResponse(
        cycle_public_id=cycle.public_id,
        total_runs=total,
        robust_count=robust,
        tentative_count=tentative,
        rejected_count=rejected,
        invalid_count=invalid,
        pending_count=pending,
        postmortem_count=pm_count,
        latest_cycle_summary_report_public_id=(
            latest_cycle_summary_report.public_id if latest_cycle_summary_report else None
        ),
        next_step_recommendations=recommendations,
    )


def get_historical_comparison_api(
    session: Session, run_public_id: str,
) -> HistoricalComparisonResponse:
    vr = get_verification_report_for_run(session, run_public_id)
    run = get_run_by_public_id(session, run_public_id)
    spec = session.get(ExperimentSpecModel, run.experiment_spec_id)
    cycle = session.get(ResearchCycleModel, run.cycle_id)
    hyp_pub_id = None
    if spec and spec.hypothesis_card_id:
        from libs.storage.models import HypothesisCardModel

        hyp = session.get(HypothesisCardModel, spec.hypothesis_card_id)
        hyp_pub_id = hyp.public_id if hyp else None
    comparisons = vr.historical_comparisons if vr else []
    prior_runs = []
    memory_references: list[dict[str, Any]] = []
    if cycle and spec:
        prior_runs = find_comparable_runs(
            session,
            run,
            spec,
            charter_id=cycle.charter_id,
        )
        memory_references = collect_historical_memory_refs(session, prior_runs)
    total_prior = len(prior_runs) if prior_runs else (
        len({c.get("prior_run_public_id") for c in comparisons}) if comparisons else 0
    )
    charter = session.get(ResearchCharterModel, cycle.charter_id) if cycle else None
    return HistoricalComparisonResponse(
        run_public_id=run.public_id,
        experiment_spec_public_id=spec.public_id if spec else "",
        hypothesis_public_id=hyp_pub_id,
        charter_public_id=charter.public_id if charter else None,
        comparison_scope="same_charter",
        comparisons=comparisons,
        memory_references=memory_references,
        total_prior_runs=total_prior,
    )
