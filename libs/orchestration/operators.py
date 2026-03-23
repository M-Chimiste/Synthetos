from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.adapters.container import DockerContainerAdapter
from libs.adapters.corpus.adapter import CorpusAdapterConfig, InternalCorpusAdapter
from libs.adapters.git import GitWorktreeAdapter
from libs.adapters.literature import SourceQuery
from libs.adapters.literature.fulltext import FulltextFetcher
from libs.adapters.llm.gateway import ModelGateway
from libs.core.config import AppConfig
from libs.core.ids import generate_public_id
from libs.core.operators import (
    ContextPack,
    NextAction,
    OperatorContext,
    OperatorReport,
    OperatorResult,
    SkillExecutionOutcome,
    StatePatch,
)
from libs.core.policy import Actor, TokenScope
from libs.core.state_machine import CycleStatus
from libs.execution import (
    build_run_spec,
    classify_failure,
    collect_artifact_manifest,
    preflight_run_spec,
    stage_execution_harness,
)
from libs.literature import services as lit_svc
from libs.literature.triage import TriageRequest, triage_batch
from libs.storage.models import (
    ExperimentSpecModel,
    JobModel,
    ResearchCharterModel,
    ResearchCycleModel,
    SkillVersionModel,
    SourceRetrievalSessionModel,
)
from libs.storage.services import (
    append_run_telemetry_event,
    bind_skills_for_cycle,
    create_state_snapshot,
    get_run_by_public_id,
    normalize_source_scope,
)

log = structlog.get_logger(__name__)


def _bound_skill_context(
    session: Session,
    cycle: ResearchCycleModel,
    operator_name: str,
    *,
    influence: str = "context_and_reporting",
    payload: dict[str, object] | None = None,
) -> tuple[list[str], list[SkillExecutionOutcome]]:
    skill_keys: list[str] = []
    outcomes: list[SkillExecutionOutcome] = []
    for binding in bind_skills_for_cycle(session, cycle, operator_name):
        version = session.get(SkillVersionModel, binding.skill_version_id)
        skill_key = (
            str(version.manifest.get("id", version.public_id))
            if version is not None
            else binding.public_id
        )
        skill_keys.append(skill_key)
        outcomes.append(
            SkillExecutionOutcome(
                skill_version_public_id=version.public_id if version else "",
                skill_binding_public_id=binding.public_id,
                operator_name=operator_name,
                status="applied",
                payload={
                    "reason": binding.binding_reason,
                    "skill_key": skill_key,
                    "influence": influence,
                    **(payload or {}),
                },
            )
        )
    return skill_keys, outcomes


def _format_skill_line(skill_keys: list[str]) -> str:
    return ", ".join(skill_keys) if skill_keys else "none"


def _assign_run_public_id(
    outcomes: list[SkillExecutionOutcome], run_public_id: str
) -> list[SkillExecutionOutcome]:
    for outcome in outcomes:
        outcome.run_public_id = run_public_id
    return outcomes


def _experiment_spec_schema(spec: ExperimentSpecModel):
    from libs.schemas.domain import ExperimentSpec

    return ExperimentSpec(
        public_id=spec.public_id,
        hypothesis_public_id="",
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


def _resolve_fulltext_budget(config: AppConfig, source_scope: dict) -> int:
    policy = config.load_yaml(config.policy_config_path)
    default_budget = (
        policy.get("literature", {})
        .get("fulltext_budget", {})
        .get("max_fetches", 3)
    )
    budget = source_scope.get("fulltext_budget", {})
    if isinstance(budget, int):
        return max(0, budget)
    if isinstance(budget, dict):
        try:
            return max(0, int(budget.get("max_fetches", default_budget)))
        except (TypeError, ValueError):
            return max(0, int(default_budget))
    return max(0, int(default_budget))


def initialize_cycle_operator(
    session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    charter = session.get(ResearchCharterModel, cycle.charter_id)
    if charter is None:
        raise ValueError("Cycle is missing a charter")
    if not charter.problem_statement.strip():
        raise ValueError("Charter problem statement is required")
    if not charter.success_criteria:
        raise ValueError("Charter success criteria are required")
    if not charter.stop_conditions:
        raise ValueError("Charter stop conditions are required")

    bindings = bind_skills_for_cycle(session, cycle, job.operator_name)
    context = OperatorContext.from_actor(
        actor=actor,
        cycle_public_id=cycle.public_id,
        job_public_id=job.public_id,
        current_state=CycleStatus(cycle.current_status),
        charter={
            "title": charter.title,
            "problem_statement": charter.problem_statement,
            "success_criteria": charter.success_criteria,
            "stop_conditions": charter.stop_conditions,
        },
        context_pack=ContextPack(
            sources=["research_charter", "skill_catalog"],
            budget_tokens=2000,
            metadata={"phase": "phase0"},
        ),
    )
    report = OperatorReport(
        title=f"Initialization report for {charter.title}",
        prompt_id="prompts/planning/v1/initialize_cycle.md",
        body_markdown="\n".join(
            [
                f"# Initialization Report: {charter.title}",
                "",
                f"- Cycle: `{cycle.public_id}`",
                f"- Job: `{job.public_id}`",
                "- Problem statement present: `yes`",
                "- Success criteria present: `yes`",
                "- Stop conditions present: `yes`",
                f"- Bound skills: `{len(bindings)}`",
                "",
                "Phase 0 initialization completed successfully.",
                "",
                "## Context Snapshot",
                f"- Current state: `{context.current_state.value}`",
                f"- Sources: `{', '.join(context.context_pack.sources)}`",
            ]
        ),
    )
    skill_records: list[SkillExecutionOutcome] = []
    for binding in bindings:
        version = session.get(SkillVersionModel, binding.skill_version_id)
        skill_records.append(
            SkillExecutionOutcome(
                skill_version_public_id=version.public_id if version else "",
                skill_binding_public_id=binding.public_id,
                operator_name=job.operator_name,
                status="applied",
                payload={"reason": binding.binding_reason},
            )
        )

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason="Initialization operator completed",
            context={"bound_skill_count": len(bindings)},
        ),
        emitted_events=[
            {
                "event_type": "cycle_ready",
                "payload": {"cycle_public_id": cycle.public_id, "job_public_id": job.public_id},
            }
        ]
        + [
            {
                "event_type": "skill_bound_to_operator",
                "payload": {
                    "binding_public_id": binding.public_id,
                    "operator_name": job.operator_name,
                },
            }
            for binding in bindings
        ],
        operator_report=report,
        skill_execution_records=skill_records,
    )


# ---------------------------------------------------------------------------
# Phase 1 — Literature Intake Operators
# ---------------------------------------------------------------------------


def source_retrieval_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Retrieve papers from hybrid arXiv warehouse + internal corpus."""
    from libs.retrieval.arxiv_warehouse import ArxivWarehouseService
    from libs.verification.failure_memory import aggregate_failure_guidance

    charter = session.get(ResearchCharterModel, cycle.charter_id)
    if charter is None:
        raise ValueError("Cycle is missing a charter")

    source_scope = job.payload.get("source_scope", charter.source_scope or {})
    source_scope = normalize_source_scope(source_scope)
    overrides = job.payload.get("source_overrides", {})

    keywords = source_scope.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [keywords]
    # Extract keywords from problem statement if none specified
    if not keywords and charter.problem_statement:
        keywords = charter.problem_statement.split()[:10]
    query_text = " ".join(keywords).strip() if keywords else charter.problem_statement.strip()

    categories = source_scope.get("categories", ["cs"])
    date_from = overrides.get("date_from", source_scope.get("date_from"))
    date_until = overrides.get("date_until", source_scope.get("date_until"))
    max_results = int(overrides.get("max_results", source_scope.get("max_results", 50)))

    query = SourceQuery(
        keywords=keywords,
        categories=categories,
        date_from=date_from,
        date_until=date_until,
        max_results=max_results,
    )
    failure_guidance = aggregate_failure_guidance(session, charter_id=charter.id)
    retrieval_guidance = failure_guidance["retrieval_guidance"][:3]

    all_papers = []
    events: list[dict] = [
        {
            "event_type": "source_retrieval_started",
            "payload": {
                "cycle_public_id": cycle.public_id,
                "query": query.model_dump(),
                "retrieval_hints": retrieval_guidance,
            },
        }
    ]

    # arXiv warehouse-backed hybrid search
    arxiv_session = SourceRetrievalSessionModel(
        public_id=generate_public_id("retsess"),
        cycle_id=cycle.id,
        source_type="arxiv_warehouse",
        query_params={**query.model_dump(), "query_text": query_text},
        status="running",
    )
    session.add(arxiv_session)
    session.flush()

    try:
        warehouse = ArxivWarehouseService(config)
        parsed_until = (
            datetime.fromisoformat(date_until).replace(tzinfo=UTC)
            if date_until else None
        )
        parsed_from = (
            datetime.fromisoformat(date_from).replace(tzinfo=UTC)
            if date_from else None
        )
        warehouse.ensure_fresh(session, target_until=parsed_until)
        hits = warehouse.search(
            session,
            query_text=query_text,
            limit=max_results,
            categories=categories,
            date_from=parsed_from,
            date_until=parsed_until,
        )
        arxiv_papers = [warehouse.paper_to_raw_record(hit) for hit in hits]
        ingested = lit_svc.ingest_papers(session, cycle, arxiv_session, arxiv_papers)
        all_papers.extend(ingested)
        log.info("arxiv_retrieval_complete", count=len(ingested))
    except Exception as exc:
        arxiv_session.status = "failed"
        arxiv_session.error_message = str(exc)
        log.warning("arxiv_retrieval_failed", error=str(exc))

    # Internal corpus
    corpus_dir = Path(config.data_root) / "corpus"
    if corpus_dir.is_dir():
        corpus_session = SourceRetrievalSessionModel(
            public_id=generate_public_id("retsess"),
            cycle_id=cycle.id,
            source_type="internal_corpus",
            query_params=query.model_dump(),
            status="running",
        )
        session.add(corpus_session)
        session.flush()

        try:
            corpus_adapter = InternalCorpusAdapter(CorpusAdapterConfig(corpus_dir=corpus_dir))
            corpus_papers = corpus_adapter.search(query)
            ingested = lit_svc.ingest_papers(session, cycle, corpus_session, corpus_papers)
            all_papers.extend(ingested)
            log.info("corpus_retrieval_complete", count=len(ingested))
        except Exception as exc:
            corpus_session.status = "failed"
            corpus_session.error_message = str(exc)
            log.warning("corpus_retrieval_failed", error=str(exc))

    events.append({
        "event_type": "papers_ingested",
        "payload": {
            "cycle_public_id": cycle.public_id,
            "total_papers": len(all_papers),
        },
    })

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason="Source retrieval completed",
            context={"phase": "intake_retrieval", "papers_ingested": len(all_papers)},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Source retrieval for {charter.title}",
            prompt_id="n/a",
            body_markdown="\n".join([
                f"# Source Retrieval Report: {charter.title}",
                "",
                f"- Total papers ingested: **{len(all_papers)}**",
                f"- Source scope mode: {source_scope.get('mode', 'internal+arxiv')}",
                (
                    f"- Keywords: {', '.join(keywords)}"
                    if keywords
                    else "- Keywords: derived from problem statement"
                ),
                f"- Hybrid query text: {query_text}",
                f"- Query categories: {', '.join(categories)}",
                f"- Date range: {date_from or 'any'} to {date_until or 'any'}",
                (
                    "- Fulltext budget: "
                    f"{source_scope.get('fulltext_budget', {}).get('max_fetches', 'n/a')}"
                ),
                (
                    "- Failure-memory retrieval hints: "
                    + "; ".join(
                        f"{item.get('query')} ({item.get('rationale', 'no rationale')})"
                        for item in retrieval_guidance
                    )
                    if retrieval_guidance
                    else "- Failure-memory retrieval hints: none"
                ),
            ]),
        ),
        next_actions=[
            NextAction(
                action="literature_screen",
                payload={"cycle_public_id": cycle.public_id},
            ),
        ],
    )


def literature_screen_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Screen papers by title + abstract using LLM triage."""
    charter = session.get(ResearchCharterModel, cycle.charter_id)
    if charter is None:
        raise ValueError("Cycle is missing a charter")

    skill_keys, skill_outcomes = _bound_skill_context(session, cycle, job.operator_name)
    batch_size = 20
    papers = lit_svc.get_papers_for_screening(session, cycle.id, batch_size=batch_size)

    if not papers:
        # No more papers to screen — move to shortlisting
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="All papers screened",
                context={"phase": "intake_screening", "remaining": 0},
            ),
            emitted_events=[{
                "event_type": "screening_batch_completed",
                "payload": {
                    "cycle_public_id": cycle.public_id,
                    "screened_in_batch": 0,
                    "all_done": True,
                },
            }],
            operator_report=OperatorReport(
                title="Literature screening complete",
                prompt_id="prompts/literature/v1/title_abstract_triage.md",
                body_markdown="\n".join([
                    "All papers screened. Moving to shortlisting.",
                    "",
                    f"- Bound skills: { _format_skill_line(skill_keys) }",
                ]),
            ),
            skill_execution_records=skill_outcomes,
            next_actions=[
                NextAction(
                    action="shortlist_rank",
                    payload={"cycle_public_id": cycle.public_id},
                ),
            ],
        )

    # Build triage requests
    triage_requests = [
        TriageRequest(
            paper_id=paper.public_id,
            title=paper.title,
            abstract=paper.abstract,
            charter_problem=charter.problem_statement,
            charter_criteria=charter.success_criteria or {},
        )
        for paper in papers
    ]

    gateway = ModelGateway.from_config(config)
    triage_route = gateway.resolve_route("triage")
    responses = triage_batch(
        gateway,
        triage_requests,
        preferred_route_id=triage_route.id,
    )

    # Record decisions
    response_map = {r.paper_id: r for r in responses}
    events: list[dict] = []
    for paper in papers:
        resp = response_map.get(paper.public_id)
        if resp is None:
            continue
        lit_svc.record_screening_decision(
            session,
            paper=paper,
            decision=resp.decision,
            score=resp.score,
            rationale=resp.rationale,
            model_route_id=triage_route.id,
            prompt_id="prompts/literature/v1/title_abstract_triage.md",
            batch_index=0,
        )
        events.append({
            "event_type": "paper_title_abstract_screened",
            "payload": {
                "paper_public_id": paper.public_id,
                "decision": resp.decision,
                "score": resp.score,
            },
        })

    events.append({
        "event_type": "screening_batch_completed",
        "payload": {
            "cycle_public_id": cycle.public_id,
            "screened_in_batch": len(papers),
            "all_done": False,
        },
    })

    # Check if more papers remain
    remaining = lit_svc.get_papers_for_screening(session, cycle.id, batch_size=1)
    if remaining:
        next_op = "literature_screen"
    else:
        next_op = "shortlist_rank"

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Screened {len(papers)} papers",
            context={"phase": "intake_screening", "screened_count": len(papers)},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Screening batch ({len(papers)} papers)",
            prompt_id="prompts/literature/v1/title_abstract_triage.md",
            body_markdown="\n".join([
                "# Screening Batch Report",
                "",
                f"- Papers screened in this batch: **{len(papers)}**",
                f"- Model route: **{triage_route.id}**",
                f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                f"- Next step: **{next_op}**",
            ]),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[
            NextAction(
                action=next_op,
                payload={"cycle_public_id": cycle.public_id},
            ),
        ],
    )


def shortlist_rank_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Rank screened papers and identify escalation candidates."""
    charter = session.get(ResearchCharterModel, cycle.charter_id)
    charter_title = charter.title if charter else cycle.public_id
    skill_keys, skill_outcomes = _bound_skill_context(session, cycle, job.operator_name)

    max_shortlist = 20
    shortlisted = lit_svc.compute_shortlist(session, cycle.id, max_shortlist=max_shortlist)

    events: list[dict] = [
        {
            "event_type": "paper_shortlisted",
            "payload": {
                "paper_public_id": paper.public_id,
                "rank": paper.shortlist_rank,
                "score": paper.triage_score,
                "shortlist_reason": paper.shortlist_reason,
            },
        }
        for paper in shortlisted
    ]
    events.extend([
        {
            "event_type": "paper_shortlist_finalized",
            "payload": {
                "paper_public_id": paper.public_id,
                "rank": paper.shortlist_rank,
                "shortlist_reason": paper.shortlist_reason,
            },
        }
        for paper in shortlisted
    ])
    events.append({
        "event_type": "shortlist_decisions_finalized",
        "payload": {
            "cycle_public_id": cycle.public_id,
            "shortlisted_count": len(shortlisted),
        },
    })

    escalation_candidates = lit_svc.get_escalation_candidates(session, cycle.id)
    if escalation_candidates:
        next_op = "fulltext_escalation"
    else:
        next_op = "literature_report"

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Shortlisted {len(shortlisted)} papers",
            context={"phase": "intake_shortlisting", "shortlisted": len(shortlisted)},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Shortlist for {charter_title}",
            prompt_id="prompts/literature/v1/shortlist_ranking.md",
            body_markdown="\n".join([
                f"# Shortlist Report: {charter_title}",
                "",
                f"- Shortlisted papers: **{len(shortlisted)}**",
                f"- Escalation candidates: **{len(escalation_candidates)}**",
                f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                f"- Next step: **{next_op}**",
            ]),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[
            NextAction(
                action=next_op,
                payload={"cycle_public_id": cycle.public_id},
            ),
        ],
    )


def fulltext_escalation_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Fetch full text for escalation candidates. HTML first, PDF fallback."""
    charter = session.get(ResearchCharterModel, cycle.charter_id)
    source_scope = normalize_source_scope((charter.source_scope if charter else {}) or {})
    max_fetches = _resolve_fulltext_budget(config, source_scope)
    all_candidates = lit_svc.get_escalation_candidates(session, cycle.id)
    candidates, skipped_count = lit_svc.select_escalation_candidates(
        session,
        cycle.id,
        max_fetches=max_fetches,
    )
    skill_keys, skill_outcomes = _bound_skill_context(session, cycle, job.operator_name)
    artifact_dir = Path(config.data_root) / "artifacts" / "literature"
    fetcher = FulltextFetcher(artifact_dir=artifact_dir)

    events: list[dict] = []
    fetched_count = 0

    for paper in candidates:
        reason = lit_svc.build_escalation_reason(paper)
        events.append({
            "event_type": "paper_escalation_decision_finalized",
            "payload": {
                "paper_public_id": paper.public_id,
                "reason": reason,
                "budget_limit": max_fetches,
            },
        })
        events.append({
            "event_type": "fulltext_fetch_requested",
            "payload": {"paper_public_id": paper.public_id, "reason": reason},
        })

        result = None
        # Try HTML first (arXiv papers only)
        if paper.source_type == "arxiv":
            result = fetcher.fetch_html(paper.external_id, reason)

        # PDF fallback
        if result is None and paper.pdf_url:
            result = fetcher.fetch_pdf(paper.pdf_url, paper.external_id, reason)

        if result is not None:
            lit_svc.record_escalation(
                session, paper,
                content_type=result.content_type,
                artifact_path=result.artifact_path,
                reason=reason,
            )
            fetched_count += 1
            events.append({
                "event_type": "fulltext_fetch_completed",
                "payload": {
                    "paper_public_id": paper.public_id,
                    "content_type": result.content_type,
                    "byte_count": result.byte_count,
                },
            })
        else:
            log.warning("fulltext_fetch_skipped", paper_id=paper.public_id)
            events.append({
                "event_type": "fulltext_fetch_skipped",
                "payload": {
                    "paper_public_id": paper.public_id,
                    "reason": reason,
                },
            })

    if skipped_count:
        events.append({
            "event_type": "fulltext_budget_exhausted",
            "payload": {
                "cycle_public_id": cycle.public_id,
                "candidate_count": len(all_candidates),
                "selected_count": len(candidates),
                "skipped_count": skipped_count,
                "budget_limit": max_fetches,
            },
        })

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Fetched full text for {fetched_count} papers",
            context={
                "phase": "intake_escalation",
                "fetched_count": fetched_count,
                "budget_limit": max_fetches,
                "skipped_due_to_budget": skipped_count,
            },
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Fulltext escalation ({fetched_count} fetched)",
            prompt_id="prompts/literature/v1/escalation_rationale.md",
            body_markdown="\n".join([
                "# Fulltext Escalation Report",
                "",
                f"- Candidates considered: **{len(all_candidates)}**",
                f"- Budget limit: **{max_fetches}**",
                f"- Selected for escalation: **{len(candidates)}**",
                f"- Skipped due to budget: **{skipped_count}**",
                f"- Successfully fetched: **{fetched_count}**",
                f"- Bound skills: **{_format_skill_line(skill_keys)}**",
            ]),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[
            NextAction(
                action="literature_report",
                payload={"cycle_public_id": cycle.public_id},
            ),
        ],
    )


def literature_report_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Generate the literature screening report."""
    charter = session.get(ResearchCharterModel, cycle.charter_id)
    charter_title = charter.title if charter else cycle.public_id

    markdown = lit_svc.build_screening_report_markdown(session, cycle, charter_title)

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason="Literature screening report generated",
            context={"phase": "intake_complete"},
        ),
        emitted_events=[{
            "event_type": "literature_report_generated",
            "payload": {"cycle_public_id": cycle.public_id},
        }],
        operator_report=OperatorReport(
            title=f"Literature Screening Report: {charter_title}",
            prompt_id="prompts/literature/v1/screening_report.md",
            report_type="literature_screening_report",
            body_markdown=markdown,
        ),
    )


# ---------------------------------------------------------------------------
# Phase 2 — Evidence, Hypotheses, Protocol Operators
# ---------------------------------------------------------------------------


def evidence_extraction_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Extract evidence cards from shortlisted papers."""
    from libs.ideation import services as ideation_svc
    from libs.ideation.extraction import EvidenceExtractionRequest, extract_evidence_batch

    charter = session.get(ResearchCharterModel, cycle.charter_id)
    if charter is None:
        raise ValueError("Cycle is missing a charter")

    papers = ideation_svc.get_papers_for_evidence_extraction(session, cycle.id)
    fulltext_aware = any(bool(paper.fulltext_artifact_path) for paper in papers)
    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="evidence_context_shaping",
        payload={
            "fulltext_aware": fulltext_aware,
            "read_depth_strategy": "abstract_or_fulltext",
        },
    )

    if not papers:
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="No papers eligible for evidence extraction",
                context={"phase": "evidence_extraction", "total_evidence": 0},
            ),
            emitted_events=[{
                "event_type": "evidence_extraction_complete",
                "payload": {"cycle_public_id": cycle.public_id, "total_evidence": 0},
            }],
            operator_report=OperatorReport(
                title="Evidence Extraction (no papers)",
                prompt_id="prompts/ideation/v1/evidence_extraction.md",
                body_markdown="\n".join([
                    "No shortlisted papers available for evidence extraction.",
                    "",
                    f"- Bound skills: {_format_skill_line(skill_keys)}",
                ]),
            ),
            skill_execution_records=skill_outcomes,
        )

    requests = []
    for paper in papers:
        fulltext_excerpt = None
        read_depth = "abstract"
        if paper.fulltext_artifact_path:
            try:
                text = Path(paper.fulltext_artifact_path).read_text(encoding="utf-8")
                fulltext_excerpt = text[:4000]
                read_depth = (
                    "fulltext_html" if paper.lifecycle_status == "html_fetched"
                    else "fulltext_pdf"
                )
            except Exception:
                pass

        requests.append(EvidenceExtractionRequest(
            paper_id=paper.public_id,
            title=paper.title,
            abstract=paper.abstract,
            fulltext_excerpt=fulltext_excerpt,
            charter_problem=charter.problem_statement,
            charter_criteria=charter.success_criteria or {},
        ))

    gateway = ModelGateway.from_config(config)
    responses = extract_evidence_batch(
        gateway,
        requests,
        session=session,
        cycle_id=cycle.id,
        job_id=job.id,
        invocation_parameters={
            "operator_name": job.operator_name,
            "bound_skills": skill_keys,
            "read_depth_strategy": "abstract_or_fulltext",
        },
    )

    events: list[dict] = [{
        "event_type": "evidence_extraction_started",
        "payload": {"cycle_public_id": cycle.public_id},
    }]

    total_evidence = 0
    paper_map = {p.public_id: p for p in papers}
    for resp in responses:
        paper = paper_map.get(resp.paper_id)
        if not paper:
            continue
        read_depth = "abstract"
        if paper.fulltext_artifact_path:
            read_depth = (
                "fulltext_html" if paper.lifecycle_status == "html_fetched"
                else "fulltext_pdf"
            )
        for item in resp.evidence_items:
            card = ideation_svc.create_evidence_card(
                session, cycle.id, paper.id,
                claim=item.claim,
                evidence_type=item.evidence_type,
                strength=item.strength,
                relevance_score=item.relevance_score,
                relevance_rationale=item.relevance_rationale,
                source_section=item.source_section,
                source_quote=item.source_quote,
                read_depth=read_depth,
                model_route_id="evidence_extractor",
                prompt_id="prompts/ideation/v1/evidence_extraction.md",
            )
            events.append({
                "event_type": "evidence_card_created",
                "payload": {
                    "evidence_public_id": card.public_id,
                    "paper_public_id": paper.public_id,
                    "evidence_type": item.evidence_type,
                },
            })
            total_evidence += 1

    conflict_count, redundancy_count = ideation_svc.detect_conflicts_and_redundancy(
        session, cycle.id,
    )
    events.append({
        "event_type": "evidence_conflicts_detected",
        "payload": {
            "cycle_public_id": cycle.public_id,
            "conflict_count": conflict_count,
            "redundancy_count": redundancy_count,
        },
    })
    events.append({
        "event_type": "evidence_extraction_complete",
        "payload": {"cycle_public_id": cycle.public_id, "total_evidence": total_evidence},
    })

    if total_evidence == 0:
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason=f"No evidence extracted from {len(papers)} papers",
                context={"phase": "evidence_extraction", "total_evidence": 0},
            ),
            emitted_events=events,
            operator_report=OperatorReport(
                title="Evidence Extraction (zero evidence)",
                prompt_id="prompts/ideation/v1/evidence_extraction.md",
                body_markdown="\n".join([
                    "# Evidence Extraction Report",
                    "",
                    f"- Papers processed: **{len(papers)}**",
                    "- Evidence cards created: **0**",
                    f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                    "",
                    (
                        "No evidence cards were extracted, so the cycle will not "
                        "advance to hypothesis generation."
                    ),
                ]),
            ),
            skill_execution_records=skill_outcomes,
        )

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Extracted {total_evidence} evidence cards from {len(papers)} papers",
            context={"phase": "evidence_extraction", "total_evidence": total_evidence},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Evidence Extraction ({total_evidence} cards)",
            prompt_id="prompts/ideation/v1/evidence_extraction.md",
            body_markdown="\n".join([
                "# Evidence Extraction Report",
                "",
                f"- Papers processed: **{len(papers)}**",
                f"- Evidence cards created: **{total_evidence}**",
                f"- Conflicts detected: **{conflict_count}**",
                f"- Redundancies detected: **{redundancy_count}**",
                f"- Bound skills: **{_format_skill_line(skill_keys)}**",
            ]),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[
            NextAction(
                action="hypothesis_generation",
                payload={"cycle_public_id": cycle.public_id},
            ),
        ],
    )


def hypothesis_generation_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Generate candidate hypotheses from evidence cards."""
    from libs.ideation import services as ideation_svc
    from libs.ideation.hypothesis_gen import HypothesisGenRequest, generate_hypotheses

    charter = session.get(ResearchCharterModel, cycle.charter_id)
    if charter is None:
        raise ValueError("Cycle is missing a charter")

    evidence_cards = ideation_svc.list_evidence_for_cycle(session, cycle.id)
    benchmark_context_injected = False
    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="hypothesis_context_shaping",
        payload={
            "benchmark_context_injected": True,
            "evidence_required": True,
        },
    )
    benchmark_context_injected = any("benchmark_context" in key for key in skill_keys)
    for outcome in skill_outcomes:
        outcome.payload["benchmark_context_injected"] = benchmark_context_injected

    if not evidence_cards:
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="No evidence available for hypothesis generation",
                context={"phase": "hypothesis_generation", "hypothesis_count": 0},
            ),
            emitted_events=[{
                "event_type": "hypothesis_generation_skipped",
                "payload": {
                    "cycle_public_id": cycle.public_id,
                    "reason": "no_evidence",
                },
            }],
            operator_report=OperatorReport(
                title="Hypothesis Generation (skipped)",
                prompt_id="prompts/ideation/v1/hypothesis_generation.md",
                body_markdown="\n".join([
                    "No evidence cards are available, so hypothesis generation was skipped.",
                    "",
                    f"- Bound skills: {_format_skill_line(skill_keys)}",
                ]),
            ),
            skill_execution_records=skill_outcomes,
        )

    evidence_summary = [
        {
            "public_id": e.public_id,
            "claim": e.claim,
            "evidence_type": e.evidence_type,
            "strength": e.strength,
            "relevance_score": e.relevance_score,
        }
        for e in evidence_cards
    ]

    gateway = ModelGateway.from_config(config)
    request = HypothesisGenRequest(
        charter_problem=charter.problem_statement,
        charter_criteria=charter.success_criteria or {},
        evidence_summary=evidence_summary,
        num_hypotheses=5,
    )
    response = generate_hypotheses(
        gateway,
        request,
        session=session,
        cycle_id=cycle.id,
        job_id=job.id,
        invocation_parameters={
            "operator_name": job.operator_name,
            "bound_skills": skill_keys,
            "benchmark_context_injected": benchmark_context_injected,
        },
    )

    events: list[dict] = [{
        "event_type": "hypothesis_generation_started",
        "payload": {"cycle_public_id": cycle.public_id},
    }]

    created = []
    for h in response.hypotheses:
        card = ideation_svc.create_hypothesis_card(
            session, cycle.id,
            title=h.title,
            statement=h.statement,
            rationale=h.rationale,
            approach_summary=h.approach_summary,
            supporting_evidence=h.supporting_evidence_ids,
            counter_evidence=h.counter_evidence_ids,
            model_route_id="ideation",
            prompt_id="prompts/ideation/v1/hypothesis_generation.md",
        )
        created.append(card)
        events.append({
            "event_type": "hypothesis_card_created",
            "payload": {"hypothesis_public_id": card.public_id, "title": h.title},
        })

    events.append({
        "event_type": "hypothesis_generation_complete",
        "payload": {"cycle_public_id": cycle.public_id, "count": len(created)},
    })

    if not created:
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="Hypothesis generation produced no candidates",
                context={"phase": "hypothesis_generation", "hypothesis_count": 0},
            ),
            emitted_events=events,
            operator_report=OperatorReport(
                title="Hypothesis Generation (zero candidates)",
                prompt_id="prompts/ideation/v1/hypothesis_generation.md",
                body_markdown="\n".join([
                    "# Hypothesis Generation Report",
                    "",
                    f"- Evidence cards used: **{len(evidence_cards)}**",
                    "- Hypotheses generated: **0**",
                    f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                    "",
                    (
                        "No hypothesis candidates were generated, so the cycle will "
                        "not advance to critique."
                    ),
                ]),
            ),
            skill_execution_records=skill_outcomes,
        )

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Generated {len(created)} hypotheses",
            context={"phase": "hypothesis_generation", "hypothesis_count": len(created)},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Hypothesis Generation ({len(created)} candidates)",
            prompt_id="prompts/ideation/v1/hypothesis_generation.md",
            body_markdown="\n".join([
                "# Hypothesis Generation Report",
                "",
                f"- Evidence cards used: **{len(evidence_cards)}**",
                f"- Hypotheses generated: **{len(created)}**",
                f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                "",
            ] + [
                f"### {i+1}. {c.title}\n{c.statement}\n"
                for i, c in enumerate(created)
            ]),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[
            NextAction(
                action="hypothesis_critique",
                payload={"cycle_public_id": cycle.public_id},
            ),
        ],
    )


def hypothesis_critique_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Critique and rank hypotheses."""
    from libs.ideation import services as ideation_svc
    from libs.ideation.critique import CritiqueRequest, critique_hypothesis
    from libs.storage.models import EvidenceCardModel, HypothesisCardModel

    charter = session.get(ResearchCharterModel, cycle.charter_id)
    if charter is None:
        raise ValueError("Cycle is missing a charter")

    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="hypothesis_critique_scoring",
        payload={"novelty_critique_active": True},
    )
    novelty_critique_active = any("novelty_critique" in key for key in skill_keys)
    for outcome in skill_outcomes:
        outcome.payload["novelty_critique_active"] = novelty_critique_active

    hypotheses = list(
        session.scalars(
            select(HypothesisCardModel).where(
                HypothesisCardModel.cycle_id == cycle.id,
                HypothesisCardModel.status == "generated",
            )
        ).all()
    )

    if not hypotheses:
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="No generated hypotheses available for critique",
                context={"phase": "hypothesis_critique", "ranked_count": 0},
            ),
            emitted_events=[{
                "event_type": "hypothesis_critique_skipped",
                "payload": {
                    "cycle_public_id": cycle.public_id,
                    "reason": "no_generated_hypotheses",
                },
            }],
            operator_report=OperatorReport(
                title="Hypothesis Critique (skipped)",
                prompt_id="prompts/ideation/v1/hypothesis_critique.md",
                body_markdown="\n".join([
                    (
                        "No generated hypotheses are available, so critique and "
                        "portfolio ranking were skipped."
                    ),
                    "",
                    f"- Bound skills: {_format_skill_line(skill_keys)}",
                ]),
            ),
            skill_execution_records=skill_outcomes,
        )

    gateway = ModelGateway.from_config(config)
    events: list[dict] = [{
        "event_type": "hypothesis_critique_started",
        "payload": {"cycle_public_id": cycle.public_id},
    }]

    for hyp in hypotheses:
        sup_evidence: list[dict] = []
        ctr_evidence: list[dict] = []
        all_ids = list(set((hyp.supporting_evidence or []) + (hyp.counter_evidence or [])))
        if all_ids:
            ev_models = list(session.scalars(
                select(EvidenceCardModel).where(EvidenceCardModel.public_id.in_(all_ids))
            ).all())
            ev_map = {
                e.public_id: {
                    "claim": e.claim,
                    "evidence_type": e.evidence_type,
                    "strength": e.strength,
                }
                for e in ev_models
            }
            sup_evidence = [
                ev_map[eid] for eid in (hyp.supporting_evidence or []) if eid in ev_map
            ]
            ctr_evidence = [
                ev_map[eid] for eid in (hyp.counter_evidence or []) if eid in ev_map
            ]

        critique_req = CritiqueRequest(
            hypothesis_title=hyp.title,
            statement=hyp.statement,
            rationale=hyp.rationale,
            approach_summary=hyp.approach_summary,
            supporting_evidence=sup_evidence,
            counter_evidence=ctr_evidence,
            charter_problem=charter.problem_statement,
        )
        response = critique_hypothesis(
            gateway,
            critique_req,
            session=session,
            cycle_id=cycle.id,
            job_id=job.id,
            invocation_parameters={
                "operator_name": job.operator_name,
                "bound_skills": skill_keys,
                "hypothesis_public_id": hyp.public_id,
                "novelty_critique_active": novelty_critique_active,
            },
        )
        ideation_svc.record_hypothesis_critique(session, hyp, response.model_dump())

        events.append({
            "event_type": "hypothesis_critiqued",
            "payload": {
                "hypothesis_public_id": hyp.public_id,
                "novelty_score": response.novelty_score,
                "feasibility_score": response.feasibility_score,
                "impact_score": response.impact_score,
            },
        })

    ranked = ideation_svc.compute_portfolio_ranking(
        session,
        cycle.id,
        auto_approve_top_n=3,
        charter_id=charter.id,
    )
    top_hyp = ranked[0] if ranked else None

    events.append({
        "event_type": "portfolio_ranked",
        "payload": {
            "cycle_public_id": cycle.public_id,
            "top_hypothesis_public_id": top_hyp.public_id if top_hyp else None,
            "total_ranked": len(ranked),
        },
    })
    for h in ranked:
        if h.status == "approved":
            events.append({
                "event_type": "hypothesis_approved",
                "payload": {
                    "hypothesis_public_id": h.public_id,
                    "portfolio_rank": h.portfolio_rank,
                },
            })
    events.append({
        "event_type": "hypothesis_critique_complete",
        "payload": {"cycle_public_id": cycle.public_id},
    })

    if not ranked:
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="Hypothesis critique produced no ranked portfolio",
                context={"phase": "hypothesis_critique", "ranked_count": 0},
            ),
            emitted_events=events,
            operator_report=OperatorReport(
                title="Hypothesis Critique (zero ranked)",
                prompt_id="prompts/ideation/v1/hypothesis_critique.md",
                body_markdown="\n".join([
                    "# Hypothesis Critique & Ranking Report",
                    "",
                    "- Portfolio ranked: **0**",
                    f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                    "",
                    "No ranked hypotheses were produced, so protocol compilation was not queued.",
                ]),
            ),
            skill_execution_records=skill_outcomes,
        )

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Critiqued and ranked {len(ranked)} hypotheses",
            context={"phase": "hypothesis_critique", "ranked_count": len(ranked)},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Hypothesis Critique ({len(ranked)} ranked)",
            prompt_id="prompts/ideation/v1/hypothesis_critique.md",
            body_markdown="\n".join([
                "# Hypothesis Critique & Ranking Report",
                "",
                f"- Hypotheses critiqued: **{len(hypotheses)}**",
                f"- Portfolio ranked: **{len(ranked)}**",
                f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                "",
            ] + [
                f"### #{h.portfolio_rank}. {h.title}\n"
                f"- Score: {h.portfolio_score:.4f}\n"
                f"- Status: {h.status}\n"
                f"- Novelty: {h.novelty_score}, "
                f"Feasibility: {h.feasibility_score}, "
                f"Impact: {h.impact_score}\n"
                for h in ranked
            ]),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[
            NextAction(
                action="protocol_compilation",
                payload={"cycle_public_id": cycle.public_id},
            ),
        ],
    )


def protocol_compilation_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Compile an experiment spec from the top-ranked approved hypothesis."""
    from libs.ideation import services as ideation_svc
    from libs.ideation.protocol_compiler import ProtocolCompileRequest, compile_protocol
    from libs.storage.models import EvidenceCardModel

    charter = session.get(ResearchCharterModel, cycle.charter_id)
    if charter is None:
        raise ValueError("Cycle is missing a charter")

    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="protocol_context_shaping",
        payload={
            "benchmark_context_injected": True,
            "protocol_drafting_active": True,
        },
    )
    benchmark_context_injected = any("benchmark_context" in key for key in skill_keys)
    protocol_drafting_active = any("protocol_drafting" in key for key in skill_keys)
    for outcome in skill_outcomes:
        outcome.payload["benchmark_context_injected"] = benchmark_context_injected
        outcome.payload["protocol_drafting_active"] = protocol_drafting_active

    approved = ideation_svc.get_approved_hypotheses(session, cycle.id)
    if not approved:
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="No approved hypotheses for protocol compilation",
                context={"phase": "protocol_compilation"},
            ),
            emitted_events=[{
                "event_type": "protocol_compilation_started",
                "payload": {
                    "cycle_public_id": cycle.public_id,
                    "hypothesis_public_id": None,
                },
            }],
            operator_report=OperatorReport(
                title="Protocol Compilation (no approved hypotheses)",
                prompt_id="prompts/ideation/v1/protocol_compilation.md",
                body_markdown="\n".join([
                    "No approved hypotheses available for protocol compilation.",
                    "",
                    f"- Bound skills: {_format_skill_line(skill_keys)}",
                ]),
            ),
            skill_execution_records=skill_outcomes,
        )

    hyp = approved[0]
    sup_ids = hyp.supporting_evidence or []
    evidence_data: list[dict] = []
    if sup_ids:
        ev_models = list(session.scalars(
            select(EvidenceCardModel).where(EvidenceCardModel.public_id.in_(sup_ids))
        ).all())
        evidence_data = [
            {"claim": e.claim, "evidence_type": e.evidence_type, "strength": e.strength}
            for e in ev_models
        ]

    events: list[dict] = [{
        "event_type": "protocol_compilation_started",
        "payload": {
            "cycle_public_id": cycle.public_id,
            "hypothesis_public_id": hyp.public_id,
        },
    }]

    gateway = ModelGateway.from_config(config)
    compile_req = ProtocolCompileRequest(
        hypothesis={
            "title": hyp.title,
            "statement": hyp.statement,
            "rationale": hyp.rationale,
            "approach_summary": hyp.approach_summary,
        },
        evidence=evidence_data,
        charter_problem=charter.problem_statement,
        charter_criteria=charter.success_criteria or {},
        constraints=charter.constraints or {},
    )
    response = compile_protocol(
        gateway,
        compile_req,
        session=session,
        cycle_id=cycle.id,
        job_id=job.id,
        invocation_parameters={
            "operator_name": job.operator_name,
            "bound_skills": skill_keys,
            "hypothesis_public_id": hyp.public_id,
            "benchmark_context_injected": benchmark_context_injected,
            "protocol_drafting_active": protocol_drafting_active,
        },
    )

    spec = ideation_svc.create_experiment_spec(
        session, cycle.id, hyp.id,
        spec_data=response.model_dump(),
        model_route_id="protocol_drafter",
        prompt_id="prompts/ideation/v1/protocol_compilation.md",
    )

    events.append({
        "event_type": "experiment_spec_created",
        "payload": {
            "spec_public_id": spec.public_id,
            "hypothesis_public_id": hyp.public_id,
            "status": spec.status,
        },
    })

    issues = ideation_svc.validate_experiment_spec(spec)
    spec.validation_issues = issues
    blocking = [i for i in issues if i.get("severity") == "blocking"]

    if blocking:
        ideation_svc.reject_experiment_spec(
            session, spec,
            reason="; ".join(i["issue"] for i in blocking),
        )
        events.append({
            "event_type": "experiment_spec_rejected",
            "payload": {
                "spec_public_id": spec.public_id,
                "reason": spec.rejection_reason,
            },
        })
    else:
        spec.status = "valid"
        session.flush()
        events.append({
            "event_type": "experiment_spec_validated",
            "payload": {
                "spec_public_id": spec.public_id,
                "status": "valid",
                "issue_count": len(issues),
            },
        })

    hyp.status = "compiled"
    session.flush()

    events.append({
        "event_type": "phase2_report_generated",
        "payload": {"cycle_public_id": cycle.public_id},
    })

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Protocol compiled — spec {spec.status}",
            context={"phase": "phase2_complete", "spec_status": spec.status},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Protocol Compilation: {spec.title}",
            prompt_id="prompts/ideation/v1/protocol_compilation.md",
            body_markdown="\n".join([
                "# Protocol Compilation Report",
                "",
                f"- Hypothesis: **{hyp.title}**",
                f"- Spec: **{spec.title}**",
                f"- Status: **{spec.status}**",
                f"- Validation issues: **{len(issues)}**",
                f"- GPU required: **{spec.gpu_required}**",
                f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                "",
                "## Objective",
                spec.objective or "(empty)",
                "",
                "## Baseline",
                spec.baseline_description or "(empty)",
                "",
                "## Method",
                spec.method_description or "(empty)",
            ]),
        ),
        skill_execution_records=skill_outcomes,
    )


# ---------------------------------------------------------------------------
# Phase 3 — Run execution lab
# ---------------------------------------------------------------------------


def run_prepare_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    run = get_run_by_public_id(session, job.payload["run_public_id"])
    spec = session.get(ExperimentSpecModel, run.experiment_spec_id)
    if spec is None:
        raise ValueError("Run is missing its experiment spec")
    if spec.status not in {"valid", "approved"}:
        raise ValueError("Experiment spec must be valid or approved before run preparation")

    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="execution_patch_authoring",
        payload={
            "prompt_id": "prompts/coding/v1/experiment_patch_author.md",
            "harness_template": "offline_baseline",
        },
    )
    _assign_run_public_id(skill_outcomes, run.public_id)

    worktree = GitWorktreeAdapter(Path.cwd()).create_worktree(config.workspaces_dir, run.public_id)
    spec_schema = _experiment_spec_schema(spec)
    paths = stage_execution_harness(
        config=config,
        workspace_path=worktree.workspace_path,
        run_public_id=run.public_id,
        experiment_spec=spec_schema,
    )
    patch_archive_path = GitWorktreeAdapter(Path.cwd()).capture_patch_archive(
        worktree.workspace_path,
        paths.patch_archive_path,
    )
    run_spec = build_run_spec(
        config=config,
        run_public_id=run.public_id,
        workspace_path=worktree.workspace_path,
        experiment_spec=spec_schema,
        execution_profile=run.execution_profile,
        patch_archive_path=patch_archive_path,
        artifact_root=paths.artifact_root,
        env_overrides=run.env_vars,
    )
    issues = preflight_run_spec(run_spec)

    run.workspace_path = run_spec.workspace_path
    run.artifact_root = run_spec.artifact_output_path
    run.stdout_path = str(paths.stdout_path)
    run.stderr_path = str(paths.stderr_path)
    run.patch_archive_path = str(patch_archive_path)
    run.base_commit = worktree.base_commit
    run.base_branch = worktree.base_branch
    run.image = run_spec.image
    run.build_recipe = run_spec.build_recipe
    run.command = run_spec.command
    run.env_vars = run_spec.env_vars
    run.mounts = run_spec.mounts
    run.hardware_profile = run_spec.hardware_profile
    run.timeout_seconds = run_spec.timeout_seconds
    run.memory_limit_mb = run_spec.memory_limit_mb
    run.cpu_limit = run_spec.cpu_limit
    run.gpu_enabled = run_spec.gpu_enabled
    run.network_mode = run_spec.network_mode
    run.bound_skill_keys = skill_keys
    run.prompt_lineage = [
        {"prompt_id": "prompts/coding/v1/experiment_patch_author.md", "mode": "deterministic"}
    ]
    run.model_lineage = [{"mode": "deterministic_patch_authoring"}]
    run.attempt_count += 1

    events = [
        {
            "event_type": "run_preparation_started",
            "payload": {"cycle_public_id": cycle.public_id, "run_public_id": run.public_id},
        }
    ]
    if issues:
        run.status = "failed"
        run.failure_classification = "harness_mismatch"
        run.last_error = "; ".join(issues)
        events.append(
            {
                "event_type": "run_preparation_failed",
                "payload": {
                    "run_public_id": run.public_id,
                    "issues": issues,
                },
            }
        )
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="Run preparation failed preflight",
                context={"run_public_id": run.public_id, "phase": "run_prepare"},
            ),
            emitted_events=events,
            operator_report=OperatorReport(
                title=f"Run Preparation Failed: {run.public_id}",
                prompt_id="prompts/coding/v1/experiment_patch_author.md",
                body_markdown="\n".join(
                    [
                        "# Run Preparation",
                        "",
                        f"- Run: **{run.public_id}**",
                        f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                        "",
                        "## Preflight issues",
                        *[f"- {issue}" for issue in issues],
                    ]
                ),
            ),
            skill_execution_records=skill_outcomes,
        )

    run.status = "ready_to_execute"
    events.append(
        {
            "event_type": "run_prepared",
            "payload": {
                "run_public_id": run.public_id,
                "workspace_path": run.workspace_path,
                "patch_archive_path": run.patch_archive_path,
            },
        }
    )
    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason="Run prepared for execution",
            context={"run_public_id": run.public_id, "phase": "run_prepare"},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Run Preparation: {run.public_id}",
            prompt_id="prompts/coding/v1/experiment_patch_author.md",
            body_markdown="\n".join(
                [
                    "# Run Preparation",
                    "",
                    f"- Run: **{run.public_id}**",
                    f"- Experiment spec: **{spec.public_id}**",
                    f"- Execution profile: **{run.execution_profile}**",
                    f"- Patch archive: **{run.patch_archive_path}**",
                    f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                ]
            ),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[NextAction(action="run_execute", payload=job.payload)],
    )


def run_execute_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    run = get_run_by_public_id(session, job.payload["run_public_id"])
    if run.status == "cancelled":
        return OperatorResult(
            state_patch=StatePatch(
                target_state=CycleStatus.READY,
                reason="Run already cancelled before execution",
                context={"run_public_id": run.public_id, "phase": "run_execute"},
            ),
            emitted_events=[],
            operator_report=OperatorReport(
                title=f"Run Execution Skipped: {run.public_id}",
                prompt_id="prompts/coding/v1/experiment_patch_author.md",
                body_markdown="Run was cancelled before container execution started.",
            ),
        )

    telemetry_settings = config.load_yaml(config.execution_settings_path).get("telemetry", {})
    adapter = DockerContainerAdapter(
        poll_interval_seconds=float(telemetry_settings.get("poll_interval_seconds", 1))
    )

    run.status = "running"
    run.started_at = run.started_at or datetime.now(UTC)
    append_run_telemetry_event(
        session,
        run=run,
        event_type="run_started",
        payload={"run_public_id": run.public_id},
    )
    create_state_snapshot(
        session,
        cycle=cycle,
        target_state=CycleStatus.RUNNING,
        actor=actor,
        reason="Container execution starting",
        context={"run_public_id": run.public_id},
        scope_used=TokenScope.RUNS_CONTROL.value,
    )
    session.commit()

    def _status_checker() -> str | None:
        session.refresh(run)
        if run.status in {"pause_requested", "cancel_requested"}:
            return run.status
        return None

    def _telemetry_callback(
        event_type: str, payload: dict[str, object], stream: str | None, message: str | None
    ) -> None:
        append_run_telemetry_event(
            session,
            run=run,
            event_type=event_type,
            payload=payload,
            stream=stream,
            message=message,
        )
        session.commit()

    from libs.schemas.domain import RunSpec

    execution_result = adapter.run(
        spec=RunSpec(
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
        stdout_path=Path(run.stdout_path or ""),
        stderr_path=Path(run.stderr_path or ""),
        telemetry_callback=_telemetry_callback,
        status_checker=_status_checker,
        container_name=f"synthetos-{run.public_id[:18]}",
    )

    artifact_manifest = collect_artifact_manifest(Path(run.artifact_root))
    metrics_path = artifact_manifest.get("metrics_path")
    metrics_summary = {}
    if metrics_path and Path(str(metrics_path)).exists():
        metrics_summary = json.loads(Path(str(metrics_path)).read_text(encoding="utf-8"))

    run.latest_resource_snapshot = execution_result.latest_resource_snapshot
    run.artifact_manifest = artifact_manifest
    run.metrics_summary = metrics_summary
    run.exit_code = execution_result.exit_code
    run.completed_at = datetime.now(UTC)
    run.failure_classification = classify_failure(
        exit_code=execution_result.exit_code,
        interrupted_status=execution_result.interrupted_status,
        artifact_manifest=artifact_manifest,
        stderr_path=Path(run.stderr_path or ""),
    )
    run.last_error = None if run.failure_classification is None else run.failure_classification
    if execution_result.interrupted_status == "paused":
        run.status = "paused"
    elif execution_result.interrupted_status == "cancelled":
        run.status = "cancelled"
    elif execution_result.interrupted_status == "timed_out":
        run.status = "failed"
    elif run.failure_classification is None:
        run.status = "succeeded"
    else:
        run.status = "failed"

    events = [
        {
            "event_type": "run_execution_complete",
            "payload": {
                "cycle_public_id": cycle.public_id,
                "run_public_id": run.public_id,
                "status": run.status,
                "failure_classification": run.failure_classification,
            },
        }
    ]
    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Run execution finished with status {run.status}",
            context={"run_public_id": run.public_id, "phase": "run_execute"},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Run Execution: {run.public_id}",
            prompt_id="prompts/coding/v1/experiment_patch_author.md",
            body_markdown="\n".join(
                [
                    "# Run Execution",
                    "",
                    f"- Run: **{run.public_id}**",
                    f"- Status: **{run.status}**",
                    f"- Exit code: **{run.exit_code}**",
                    f"- Failure classification: **{run.failure_classification or 'none'}**",
                ]
            ),
        ),
        next_actions=[NextAction(action="run_finalize", payload=job.payload)],
    )


def run_finalize_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    run = get_run_by_public_id(session, job.payload["run_public_id"])
    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="run_evaluation_and_summary",
        payload={"artifact_manifest_present": bool(run.artifact_manifest)},
    )
    _assign_run_public_id(skill_outcomes, run.public_id)

    if run.status in {"succeeded", "cancelled"} and run.workspace_path:
        try:
            GitWorktreeAdapter(Path.cwd()).remove_worktree(Path(run.workspace_path))
        except Exception:
            log.warning("worktree_cleanup_failed", workspace_path=run.workspace_path)

    events = [
        {
            "event_type": "run_finalized",
            "payload": {
                "cycle_public_id": cycle.public_id,
                "run_public_id": run.public_id,
                "status": run.status,
            },
        }
    ]
    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason="Run finalized",
            context={"run_public_id": run.public_id, "phase": "phase3_complete"},
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Run Summary: {run.public_id}",
            prompt_id="prompts/coding/v1/experiment_patch_author.md",
            report_type="run_summary_report",
            body_markdown="\n".join(
                [
                    "# Run Summary",
                    "",
                    f"- Run: **{run.public_id}**",
                    f"- Status: **{run.status}**",
                    f"- Execution profile: **{run.execution_profile}**",
                    f"- Metrics: `{json.dumps(run.metrics_summary or {}, sort_keys=True)}`",
                    f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                    "",
                    f"- Artifact root: `{run.artifact_root}`",
                ]
            ),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[NextAction(action="run_verify", payload={"run_public_id": run.public_id})],
    )


def run_retry_repair_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    run = get_run_by_public_id(session, job.payload["run_public_id"])
    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="run_repair_revision",
        payload={
            "prompt_id": "prompts/coding/v1/experiment_repair.md",
            "failure_classification": run.failure_classification,
        },
    )
    _assign_run_public_id(skill_outcomes, run.public_id)

    repair_path = Path(run.workspace_path) / "generated_runs" / run.public_id / "repair_notes.json"
    repair_path.parent.mkdir(parents=True, exist_ok=True)
    repair_path.write_text(
        json.dumps(
            {
                "run_public_id": run.public_id,
                "failure_classification": run.failure_classification,
                "repaired_at": datetime.now(UTC).isoformat(),
                "strategy": "deterministic_harness_retry",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    run.status = "ready_to_execute"
    run.last_error = None
    run.prompt_lineage = [
        *list(run.prompt_lineage or []),
        {"prompt_id": "prompts/coding/v1/experiment_repair.md", "mode": "deterministic"},
    ]
    run.model_lineage = [*list(run.model_lineage or []), {"mode": "deterministic_repair"}]

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason="Run repair prepared for retry",
            context={"run_public_id": run.public_id, "phase": "run_retry_repair"},
        ),
        emitted_events=[
            {
                "event_type": "run_repair_prepared",
                "payload": {
                    "run_public_id": run.public_id,
                    "failure_classification": run.failure_classification,
                },
            }
        ],
        operator_report=OperatorReport(
            title=f"Run Repair: {run.public_id}",
            prompt_id="prompts/coding/v1/experiment_repair.md",
            body_markdown="\n".join(
                [
                    "# Run Repair",
                    "",
                    f"- Run: **{run.public_id}**",
                    f"- Failure classification: **{run.failure_classification}**",
                    f"- Bound skills: **{_format_skill_line(skill_keys)}**",
                ]
            ),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[NextAction(action="run_execute", payload=job.payload)],
    )


# ---------------------------------------------------------------------------
# Phase 4 — Verification, Historical Comparison, Failure Memory
# ---------------------------------------------------------------------------


def run_verify_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Run verification checks and determine outcome for a completed run."""
    from libs.storage.services import (
        create_verification_report,
    )
    from libs.verification.checks import (
        check_artifacts_present,
        check_leakage_signals,
        check_metric_sanity,
        check_output_contract,
        compare_to_baseline,
        validate_split,
    )
    from libs.verification.historical import (
        collect_historical_memory_refs,
        compare_to_historical,
        find_comparable_runs,
    )
    from libs.verification.outcome import determine_outcome
    from libs.verification.recommendations import build_rerun_note

    run = get_run_by_public_id(session, job.payload["run_public_id"])
    spec = session.get(ExperimentSpecModel, run.experiment_spec_id)
    if spec is None:
        raise ValueError("Run is missing its experiment spec")

    charter = session.get(ResearchCharterModel, cycle.charter_id)
    verification_policy = (
        config.load_yaml(config.policy_config_path).get("verification", {})
    )
    require_baseline_comparison = bool(
        verification_policy.get("require_baseline_comparison", False)
    )
    require_historical_comparison = bool(
        verification_policy.get("require_historical_comparison", False)
    )
    auto_postmortem_on_failure = bool(
        verification_policy.get("auto_postmortem_on_failure", True)
    )
    leakage_check_enabled = bool(verification_policy.get("leakage_check_enabled", True))
    split_validation_enabled = bool(verification_policy.get("split_validation_enabled", True))

    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="verification_review",
        payload={"run_status": run.status, "has_metrics": bool(run.metrics_summary)},
    )
    _assign_run_public_id(skill_outcomes, run.public_id)

    # ---- Deterministic checks ----
    artifact_checks = check_artifacts_present(
        run.artifact_manifest or {},
        [],
    )
    output_contract_checks = check_output_contract(
        run.artifact_manifest or {},
        spec.expected_outputs or [],
    )
    metric_sanity_checks = check_metric_sanity(
        run.metrics_summary or {},
        spec.metrics or [],
    )
    baseline_comparison = compare_to_baseline(
        run.metrics_summary or {},
        spec.baseline_description or "",
        spec.metrics or [],
    )
    leakage_signals = (
        check_leakage_signals(
            run.metrics_summary or {},
            {"datasets": spec.datasets or [], "controls": spec.controls or []},
        )
        if leakage_check_enabled
        else [{
            "signal_name": "leakage_check_disabled",
            "detected": False,
            "detail": "Leakage checks disabled by policy",
        }]
    )
    split_validation = (
        validate_split(
            run.metrics_summary or {},
            {"datasets": spec.datasets or []},
        )
        if split_validation_enabled
        else {
            "intended_split": None,
            "actual_split": None,
            "matched": True,
            "detail": "Split validation disabled by policy",
        }
    )

    # ---- Historical comparison ----
    prior_runs = find_comparable_runs(
        session,
        run,
        spec,
        charter_id=cycle.charter_id,
    )
    historical_comparisons = compare_to_historical(
        run.metrics_summary or {},
        prior_runs,
        spec.metrics or [],
    )
    historical_memory_refs = collect_historical_memory_refs(session, prior_runs)

    # ---- Determine outcome ----
    outcome = determine_outcome(
        run_status=run.status,
        baseline_comparison=baseline_comparison,
        metric_sanity_checks=metric_sanity_checks,
        artifact_checks=artifact_checks,
        output_contract_checks=output_contract_checks,
        leakage_signals=leakage_signals,
        split_validation=split_validation,
        historical_comparisons=historical_comparisons,
        require_baseline_comparison=require_baseline_comparison,
        require_historical_comparison=require_historical_comparison,
        leakage_check_enabled=leakage_check_enabled,
        split_validation_enabled=split_validation_enabled,
    )
    rerun_note = build_rerun_note(
        outcome=outcome.value,
        run_status=run.status,
        baseline_comparison=baseline_comparison,
        historical_comparisons=historical_comparisons,
        output_contract_checks=output_contract_checks,
        metric_sanity_checks=metric_sanity_checks,
    )

    # ---- LLM review (only for non-failed runs) ----
    prompt_id = "prompts/verification/v1/verification_review.md"
    model_route_id = "deterministic"
    fail_info = run.failure_classification or "none"
    outcome_rationale = f"Run status: {run.status}. Failure: {fail_info}."
    reviewer_summary = f"Outcome: {outcome.value}. Run {run.status}."

    if run.status not in ("failed", "cancelled"):
        try:
            gateway = ModelGateway.from_config(config)
            prompt_context = {
                "charter_problem": charter.problem_statement if charter else "",
                "experiment_title": spec.title,
                "experiment_objective": spec.objective,
                "baseline_description": spec.baseline_description,
                "run_status": run.status,
                "metrics_summary": json.dumps(run.metrics_summary or {}, sort_keys=True),
                "exit_code": run.exit_code,
                "baseline_comparison": json.dumps(baseline_comparison, sort_keys=True),
                "historical_comparisons": historical_comparisons,
                "historical_memory_refs": historical_memory_refs,
                "metric_sanity_checks": metric_sanity_checks,
                "artifact_checks": artifact_checks,
                "output_contract_checks": output_contract_checks,
                "leakage_signals": leakage_signals,
                "split_validation": json.dumps(split_validation, sort_keys=True),
                "outcome": outcome.value,
            }
            from jinja2 import Template

            template_text = Path(prompt_id).read_text(encoding="utf-8")
            rendered = Template(template_text).render(**prompt_context)
            response = gateway.call_structured(
                "verifier",
                [{"role": "user", "content": rendered}],
                temperature=0.3,
                max_tokens=512,
            )
            if isinstance(response, dict):
                outcome_rationale = response.get("outcome_rationale", outcome_rationale)
                reviewer_summary = response.get("reviewer_summary", reviewer_summary)
                model_route_id = gateway.resolve_route("verifier").id
        except Exception:
            log.warning("verification_llm_review_failed", run_public_id=run.public_id)

    # ---- Persist verification report ----
    hypothesis_card_id = spec.hypothesis_card_id if spec else None
    vr = create_verification_report(
        session,
        cycle=cycle,
        run=run,
        experiment_spec=spec,
        hypothesis_card_id=hypothesis_card_id,
        outcome=outcome.value,
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
    run.verification_outcome = outcome.value
    session.flush()

    events = [
        {
            "event_type": "run_verified",
            "payload": {
                "cycle_public_id": cycle.public_id,
                "run_public_id": run.public_id,
                "outcome": outcome.value,
                "verification_report_public_id": vr.public_id,
            },
        }
    ]

    # Chain: failed/rejected → postmortem, otherwise → verification_report
    needs_postmortem = auto_postmortem_on_failure and outcome.value in ("rejected", "invalid")
    next_op = "failure_postmortem" if needs_postmortem else "verification_report"

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.VERIFYING,
            reason=f"Verification complete: {outcome.value}",
            context={
                "run_public_id": run.public_id,
                "phase": "phase4_verification",
                "outcome": outcome.value,
            },
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Verification: {run.public_id} — {outcome.value}",
            prompt_id=prompt_id,
            report_type="verification_check_report",
            body_markdown="\n".join([
                "# Verification Check Report",
                "",
                f"- Run: **{run.public_id}**",
                f"- Outcome: **{outcome.value}**",
                f"- Baseline passed: **{baseline_comparison.get('passed', 'N/A')}**",
                f"- Historical comparisons: **{len(historical_comparisons)}**",
                f"- Historical memory refs: **{len(historical_memory_refs)}**",
                f"- Artifact checks: **{len(artifact_checks)}**",
                f"- Output-contract checks: **{len(output_contract_checks)}**",
                f"- Sanity checks failed: "
                f"**{sum(1 for c in metric_sanity_checks if not c.get('passed'))}**",
                f"- Leakage signals: **{sum(1 for s in leakage_signals if s.get('detected'))}**",
                (f"- Rerun note: {rerun_note}" if rerun_note else "- Rerun note: none"),
                "",
                f"**Summary:** {reviewer_summary}",
            ]),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[NextAction(action=next_op, payload={
            "run_public_id": run.public_id,
            "verification_report_public_id": vr.public_id,
            "postmortem_skipped_by_policy": (
                not needs_postmortem and outcome.value in ("rejected", "invalid")
            ),
        })],
    )


def failure_postmortem_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Generate a structured postmortem for a failed or rejected run."""
    from libs.storage.models import VerificationReportModel
    from libs.storage.services import create_failure_postmortem
    from libs.verification.historical import find_similar_postmortems

    run = get_run_by_public_id(session, job.payload["run_public_id"])
    spec = session.get(ExperimentSpecModel, run.experiment_spec_id)
    if spec is None:
        raise ValueError("Run is missing its experiment spec")

    charter = session.get(ResearchCharterModel, cycle.charter_id)

    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="postmortem_analysis",
        payload={
            "failure_classification": run.failure_classification,
            "run_status": run.status,
        },
    )
    _assign_run_public_id(skill_outcomes, run.public_id)

    # Determine failure class and stage
    failure_class = run.failure_classification or run.verification_outcome or "unknown"
    failure_stage = "execution" if run.status == "failed" else "verification"

    # Load verification report if available
    vr_public_id = job.payload.get("verification_report_public_id")
    vr = None
    vr_id = None
    if vr_public_id:
        vr = session.scalar(
            select(VerificationReportModel).where(
                VerificationReportModel.public_id == vr_public_id
            )
        )
        vr_id = vr.id if vr else None

    # Find similar prior postmortems
    similar = find_similar_postmortems(
        session,
        failure_class,
        charter_id=cycle.charter_id,
        exclude_run_record_id=run.id,
    )
    similar_data = [
        {
            "postmortem_public_id": pm.public_id,
            "failure_class": pm.failure_class,
            "root_cause_summary": pm.root_cause_summary,
        }
        for pm in similar
    ]

    # LLM postmortem generation
    prompt_id = "prompts/verification/v1/failure_postmortem.md"
    model_route_id = "deterministic"
    root_cause_summary = f"Run failed with classification: {failure_class}."
    contributing_factors: list[dict[str, Any]] = []
    remediation_suggestions: list[dict[str, Any]] = []
    retrieval_hints: list[dict[str, Any]] = []
    protocol_update_hints: list[dict[str, Any]] = []

    # Read stderr excerpt if available
    stderr_excerpt = ""
    if run.stderr_path:
        try:
            stderr_text = Path(run.stderr_path).read_text(encoding="utf-8")
            stderr_excerpt = stderr_text[-2000:] if len(stderr_text) > 2000 else stderr_text
        except OSError:
            pass

    try:
        gateway = ModelGateway.from_config(config)
        prompt_context = {
            "charter_problem": charter.problem_statement if charter else "",
            "experiment_title": spec.title,
            "experiment_objective": spec.objective,
            "method_description": spec.method_description,
            "run_status": run.status,
            "failure_classification": failure_class,
            "failure_stage": failure_stage,
            "exit_code": run.exit_code,
            "last_error": run.last_error or "",
            "stderr_excerpt": stderr_excerpt,
            "verification_summary": vr.reviewer_summary if vr else "N/A",
            "similar_prior_failures": similar_data,
        }
        from jinja2 import Template

        template_text = Path(prompt_id).read_text(encoding="utf-8")
        rendered = Template(template_text).render(**prompt_context)
        response = gateway.call_structured(
            "verifier",
            [{"role": "user", "content": rendered}],
            temperature=0.3,
            max_tokens=1024,
        )
        if isinstance(response, dict):
            root_cause_summary = response.get("root_cause_summary", root_cause_summary)
            contributing_factors = response.get("contributing_factors", [])
            remediation_suggestions = response.get("remediation_suggestions", [])
            retrieval_hints = response.get("retrieval_hints", [])
            protocol_update_hints = response.get("protocol_update_hints", [])
            model_route_id = gateway.resolve_route("verifier").id
    except Exception:
        log.warning("postmortem_llm_generation_failed", run_public_id=run.public_id)

    # Persist postmortem
    pm = create_failure_postmortem(
        session,
        cycle=cycle,
        run=run,
        verification_report_id=vr_id,
        failure_class=failure_class,
        failure_stage=failure_stage,
        root_cause_summary=root_cause_summary,
        contributing_factors=contributing_factors,
        remediation_suggestions=remediation_suggestions,
        retrieval_hints=retrieval_hints,
        protocol_update_hints=protocol_update_hints,
        similar_prior_failures=similar_data,
        model_route_id=model_route_id,
        prompt_id=prompt_id,
    )

    events = [
        {
            "event_type": "postmortem_created",
            "payload": {
                "cycle_public_id": cycle.public_id,
                "run_public_id": run.public_id,
                "postmortem_public_id": pm.public_id,
                "failure_class": failure_class,
                "failure_stage": failure_stage,
            },
        }
    ]

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.VERIFYING,
            reason="Postmortem generated",
            context={
                "run_public_id": run.public_id,
                "phase": "phase4_postmortem",
                "postmortem_public_id": pm.public_id,
            },
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Postmortem: {run.public_id} — {failure_class}",
            prompt_id=prompt_id,
            report_type="failure_postmortem_report",
            body_markdown="\n".join([
                "# Failure Postmortem",
                "",
                f"- Run: **{run.public_id}**",
                f"- Failure class: **{failure_class}**",
                f"- Failure stage: **{failure_stage}**",
                f"- Root cause: {root_cause_summary}",
                f"- Remediation suggestions: **{len(remediation_suggestions)}**",
                f"- Retrieval hints: **{len(retrieval_hints)}**",
                f"- Similar prior failures: **{len(similar_data)}**",
                f"- Bound skills: **{_format_skill_line(skill_keys)}**",
            ]),
        ),
        skill_execution_records=skill_outcomes,
        next_actions=[NextAction(action="verification_report", payload={
            "run_public_id": run.public_id,
            "verification_report_public_id": job.payload.get("verification_report_public_id"),
            "postmortem_public_id": pm.public_id,
        })],
    )


def verification_report_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: ResearchCycleModel,
    job: JobModel,
) -> OperatorResult:
    """Generate a final human-readable verification report for a run."""
    from libs.storage.models import (
        FailurePostmortemModel,
        HypothesisCardModel,
        VerificationReportModel,
    )
    from libs.storage.services import create_report, get_verification_summary_for_cycle
    from libs.verification.failure_memory import aggregate_failure_guidance
    from libs.verification.recommendations import build_next_step_recommendations

    run = get_run_by_public_id(session, job.payload["run_public_id"])
    spec = session.get(ExperimentSpecModel, run.experiment_spec_id)
    if spec is None:
        raise ValueError("Run is missing its experiment spec")

    charter = session.get(ResearchCharterModel, cycle.charter_id)

    skill_keys, skill_outcomes = _bound_skill_context(
        session,
        cycle,
        job.operator_name,
        influence="verification_summary",
        payload={"outcome": run.verification_outcome or "unknown"},
    )
    _assign_run_public_id(skill_outcomes, run.public_id)

    # Load verification report
    vr_public_id = job.payload.get("verification_report_public_id")
    vr = None
    if vr_public_id:
        vr = session.scalar(
            select(VerificationReportModel).where(
                VerificationReportModel.public_id == vr_public_id
            )
        )

    # Load postmortem if exists
    pm_public_id = job.payload.get("postmortem_public_id")
    pm = None
    if pm_public_id:
        pm = session.scalar(
            select(FailurePostmortemModel).where(
                FailurePostmortemModel.public_id == pm_public_id
            )
        )

    # Load hypothesis
    hyp = None
    if spec.hypothesis_card_id:
        hyp = session.get(HypothesisCardModel, spec.hypothesis_card_id)

    # LLM summary generation
    prompt_id = "prompts/verification/v1/verification_summary.md"
    outcome = run.verification_outcome or "unknown"
    verification_policy = (
        config.load_yaml(config.policy_config_path).get("verification", {})
    )
    min_outcome_for_promotion = str(
        verification_policy.get("min_outcome_for_promotion", "tentative")
    )
    failure_guidance = aggregate_failure_guidance(session, charter_id=cycle.charter_id)
    retrieval_hints = list(pm.retrieval_hints or []) if pm else []
    if not retrieval_hints:
        retrieval_hints = failure_guidance["retrieval_guidance"][:3]
    protocol_update_hints = list(pm.protocol_update_hints or []) if pm else []
    recommendations = build_next_step_recommendations(
        outcome=outcome,
        min_outcome_for_promotion=min_outcome_for_promotion,
        rerun_note=vr.rerun_note if vr else None,
        retrieval_hints=retrieval_hints,
        protocol_update_hints=protocol_update_hints,
        reviewer_summary=vr.reviewer_summary if vr else None,
    )

    # Build markdown report body
    report_lines = [
        "# Verification Report",
        "",
        f"**Run:** {run.public_id}",
        f"**Status:** {run.status}",
        f"**Outcome:** {outcome}",
        f"**Execution Profile:** {run.execution_profile}",
        "",
    ]

    if vr:
        report_lines.extend([
            "## Verification Summary",
            "",
            vr.reviewer_summary,
            "",
            "## Baseline Comparison",
            "",
            f"```json\n{json.dumps(vr.baseline_comparison or {}, indent=2)}\n```",
            "",
            "## Output Contract Checks",
            "",
            f"```json\n{json.dumps(vr.output_contract_checks or [], indent=2)}\n```",
            "",
        ])
        if vr.historical_comparisons:
            report_lines.extend([
                "## Historical Comparisons",
                "",
            ])
            for comp in vr.historical_comparisons:
                report_lines.append(
                    f"- **{comp.get('metric')}**: prior={comp.get('prior_value')} "
                    f"→ current={comp.get('current_value')} (delta={comp.get('delta')})"
                )
            report_lines.append("")
        if vr.rerun_note:
            report_lines.extend([
                "## Replay / Rerun Guidance",
                "",
                vr.rerun_note,
                "",
            ])

    if pm:
        report_lines.extend([
            "## Failure Postmortem",
            "",
            f"**Failure Class:** {pm.failure_class}",
            f"**Stage:** {pm.failure_stage}",
            f"**Root Cause:** {pm.root_cause_summary}",
            "",
        ])
        if pm.remediation_suggestions:
            report_lines.append("### Remediation Suggestions")
            report_lines.append("")
            for sug in pm.remediation_suggestions:
                report_lines.append(
                    f"- [{sug.get('category', 'general')}] {sug.get('suggestion', '')}"
                )
            report_lines.append("")

    report_lines.extend([
        "## Metrics",
        "",
        f"```json\n{json.dumps(run.metrics_summary or {}, indent=2, sort_keys=True)}\n```",
        "",
    ])
    if recommendations:
        report_lines.extend([
            "## Recommendations",
            "",
        ])
        for item in recommendations:
            report_lines.append(
                f"- **{item.get('recommendation_type', 'next_step')}**: {item.get('rationale', '')}"
            )
        report_lines.append("")
    report_lines.append(f"**Bound skills:** {_format_skill_line(skill_keys)}")

    # Try LLM-enhanced summary
    try:
        gateway = ModelGateway.from_config(config)
        prompt_context = {
            "charter_problem": charter.problem_statement if charter else "",
            "experiment_title": spec.title,
            "experiment_objective": spec.objective,
            "hypothesis_statement": hyp.statement if hyp else "N/A",
            "run_public_id": run.public_id,
            "run_status": run.status,
            "execution_profile": run.execution_profile,
            "metrics_summary": json.dumps(run.metrics_summary or {}, sort_keys=True),
            "outcome": outcome,
            "outcome_rationale": vr.outcome_rationale if vr else "",
            "baseline_comparison": json.dumps(vr.baseline_comparison if vr else {}, sort_keys=True),
            "historical_comparisons": vr.historical_comparisons if vr else [],
            "output_contract_checks": json.dumps(
                vr.output_contract_checks if vr else [],
                sort_keys=True,
            ),
            "rerun_note": vr.rerun_note if vr else None,
            "postmortem": {
                "failure_class": pm.failure_class,
                "failure_stage": pm.failure_stage,
                "root_cause_summary": pm.root_cause_summary,
                "remediation_suggestions": pm.remediation_suggestions or [],
            } if pm else None,
        }
        from jinja2 import Template

        template_text = Path(prompt_id).read_text(encoding="utf-8")
        rendered = Template(template_text).render(**prompt_context)
        llm_report = gateway.call_chat_completion(
            "reporter",
            [{"role": "user", "content": rendered}],
            temperature=0.3,
            max_tokens=2048,
        )
        if llm_report:
            report_lines = [llm_report]
    except Exception:
        log.warning("verification_report_llm_failed", run_public_id=run.public_id)

    body_markdown = "\n".join(report_lines)
    cycle_summary = get_verification_summary_for_cycle(session, cycle.public_id)
    cycle_summary_lines = [
        f"# Cycle Verification Summary: {cycle.public_id}",
        "",
        f"- Total runs: **{cycle_summary.total_runs}**",
        f"- Robust: **{cycle_summary.robust_count}**",
        f"- Tentative: **{cycle_summary.tentative_count}**",
        f"- Rejected: **{cycle_summary.rejected_count}**",
        f"- Invalid: **{cycle_summary.invalid_count}**",
        f"- Pending: **{cycle_summary.pending_count}**",
        f"- Postmortems: **{cycle_summary.postmortem_count}**",
        "",
        "## Latest Recommendations",
        "",
    ]
    for item in recommendations:
        cycle_summary_lines.append(
            f"- **{item.get('recommendation_type', 'next_step')}**: {item.get('rationale', '')}"
        )
    cycle_summary_report = create_report(
        session,
        config,
        cycle=cycle,
        job=job,
        title=f"Cycle Verification Summary: {cycle.public_id}",
        report_type="verification_cycle_summary",
        body_markdown="\n".join(cycle_summary_lines),
    )
    cycle_summary_report.report_metadata = {
        **(cycle_summary_report.report_metadata or {}),
        "run_public_id": run.public_id,
    }

    events = [
        {
            "event_type": "verification_report_created",
            "payload": {
                "cycle_public_id": cycle.public_id,
                "run_public_id": run.public_id,
                "outcome": outcome,
            },
        },
        {
            "event_type": "verification_cycle_summary_created",
            "payload": {
                "cycle_public_id": cycle.public_id,
                "run_public_id": run.public_id,
                "report_public_id": cycle_summary_report.public_id,
            },
        }
    ]

    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason="Verification cycle complete",
            context={
                "run_public_id": run.public_id,
                "phase": "phase4_complete",
                "outcome": outcome,
            },
        ),
        emitted_events=events,
        operator_report=OperatorReport(
            title=f"Verification Report: {run.public_id} — {outcome}",
            prompt_id=prompt_id,
            report_type="verification_report",
            body_markdown=body_markdown,
        ),
        skill_execution_records=skill_outcomes,
    )


def arxiv_warehouse_sync_operator(
    session: Session,
    config: AppConfig,
    actor: Actor,
    cycle: Any,
    job: Any,
) -> OperatorResult:
    """Cycle-independent operator: sync arXiv warehouse in the background."""
    from libs.retrieval.arxiv_warehouse import ArxivWarehouseService

    mode = (job.payload or {}).get("mode", "full")
    warehouse = ArxivWarehouseService(config)
    if mode == "incremental":
        run = warehouse.sync_incremental(session)
    else:
        run = warehouse.sync_full(session)
    summary = (
        f"Sync mode={run.mode} source={run.source} status={run.status} "
        f"inserted={run.inserted_count} updated={run.updated_count} "
        f"reembedded={run.reembedded_count} skipped={run.skipped_count}"
    )
    return OperatorResult(
        state_patch=StatePatch(
            target_state=CycleStatus.READY,
            reason=f"Warehouse sync complete: {summary}",
        ),
        operator_report=OperatorReport(
            title="arXiv Warehouse Sync",
            body_markdown=f"## Sync Result\n\n{summary}",
            prompt_id="system:arxiv_warehouse_sync",
        ),
    )


OPERATOR_REGISTRY = {
    # Phase 0
    "initialize_cycle": initialize_cycle_operator,
    # Phase 1
    "source_retrieval": source_retrieval_operator,
    "literature_screen": literature_screen_operator,
    "shortlist_rank": shortlist_rank_operator,
    "fulltext_escalation": fulltext_escalation_operator,
    "literature_report": literature_report_operator,
    # Phase 2
    "evidence_extraction": evidence_extraction_operator,
    "hypothesis_generation": hypothesis_generation_operator,
    "hypothesis_critique": hypothesis_critique_operator,
    "protocol_compilation": protocol_compilation_operator,
    # Phase 3
    "run_prepare": run_prepare_operator,
    "run_execute": run_execute_operator,
    "run_finalize": run_finalize_operator,
    "run_retry_repair": run_retry_repair_operator,
    # Phase 4
    "run_verify": run_verify_operator,
    "failure_postmortem": failure_postmortem_operator,
    "verification_report": verification_report_operator,
    # Cycle-independent
    "arxiv_warehouse_sync": arxiv_warehouse_sync_operator,
}
