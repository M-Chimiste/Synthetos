from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from libs.adapters.arxiv.adapter import ArxivAdapterConfig, ArxivMetadataAdapter
from libs.adapters.corpus.adapter import CorpusAdapterConfig, InternalCorpusAdapter
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
from libs.core.policy import Actor
from libs.core.state_machine import CycleStatus
from libs.literature import services as lit_svc
from libs.literature.triage import TriageRequest, triage_batch
from libs.storage.models import (
    JobModel,
    ResearchCharterModel,
    ResearchCycleModel,
    SkillVersionModel,
    SourceRetrievalSessionModel,
)
from libs.storage.services import bind_skills_for_cycle, normalize_source_scope

log = structlog.get_logger(__name__)


def _bound_skill_context(
    session: Session,
    cycle: ResearchCycleModel,
    operator_name: str,
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
                    "influence": "context_and_reporting",
                },
            )
        )
    return skill_keys, outcomes


def _format_skill_line(skill_keys: list[str]) -> str:
    return ", ".join(skill_keys) if skill_keys else "none"


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
    """Retrieve papers from arXiv metadata + internal corpus."""
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

    all_papers = []
    events: list[dict] = [
        {
            "event_type": "source_retrieval_started",
            "payload": {"cycle_public_id": cycle.public_id, "query": query.model_dump()},
        }
    ]

    # arXiv metadata
    arxiv_session = SourceRetrievalSessionModel(
        public_id=generate_public_id("retsess"),
        cycle_id=cycle.id,
        source_type="arxiv_metadata",
        query_params=query.model_dump(),
        status="running",
    )
    session.add(arxiv_session)
    session.flush()

    try:
        arxiv_adapter = ArxivMetadataAdapter(ArxivAdapterConfig(max_results=max_results))
        arxiv_papers = arxiv_adapter.search(query)
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
                f"- Query categories: {', '.join(categories)}",
                f"- Date range: {date_from or 'any'} to {date_until or 'any'}",
                (
                    "- Fulltext budget: "
                    f"{source_scope.get('fulltext_budget', {}).get('max_fetches', 'n/a')}"
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


OPERATOR_REGISTRY = {
    "initialize_cycle": initialize_cycle_operator,
    "source_retrieval": source_retrieval_operator,
    "literature_screen": literature_screen_operator,
    "shortlist_rank": shortlist_rank_operator,
    "fulltext_escalation": fulltext_escalation_operator,
    "literature_report": literature_report_operator,
}
