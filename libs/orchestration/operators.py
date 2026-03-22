from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy import select
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
                body_markdown="No shortlisted papers available for evidence extraction.",
            ),
            next_actions=[
                NextAction(
                    action="hypothesis_generation",
                    payload={"cycle_public_id": cycle.public_id},
                ),
            ],
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
    responses = extract_evidence_batch(gateway, requests)

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
            ]),
        ),
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
    response = generate_hypotheses(gateway, request)

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
                "",
            ] + [
                f"### {i+1}. {c.title}\n{c.statement}\n"
                for i, c in enumerate(created)
            ]),
        ),
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

    hypotheses = list(
        session.scalars(
            select(HypothesisCardModel).where(
                HypothesisCardModel.cycle_id == cycle.id,
                HypothesisCardModel.status == "generated",
            )
        ).all()
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
        response = critique_hypothesis(gateway, critique_req)
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

    ranked = ideation_svc.compute_portfolio_ranking(session, cycle.id, auto_approve_top_n=3)
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
                body_markdown="No approved hypotheses available for protocol compilation.",
            ),
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
    response = compile_protocol(gateway, compile_req)

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
}
