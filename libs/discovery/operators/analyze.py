"""discovery_analyze operator -- runs metadata-depth LLM analysis over the
top-N reranked papers.
"""

from __future__ import annotations

import asyncio
import contextlib

from sqlalchemy import select

from libs.adapters.llm.router import ModelRouter
from libs.core.event_types import DiscoveryEvents
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.discovery.metadata_analysis import analyze_many
from libs.discovery.operators._common import (
    DiscoveryStateError,
    append_step_log,
    enqueue_next,
    load_profile,
    load_session,
    merge_stats,
    session_id_from_payload,
)
from libs.discovery.skill_support import join_skill_prompts, load_skill_prompt
from libs.storage.base import get_sync_session_factory
from libs.storage.models.papers import PaperCard

log = get_logger(__name__)

_TRIAGE_SKILL_ID = "literature.title_abstract_triage"
_ESCALATION_SKILL_ID = "literature.escalation_rationale"


def discovery_analyze_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        session_id = session_id_from_payload(op_input)
    except DiscoveryStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    with factory() as session:
        try:
            discovery = load_session(session, session_id)
            profile = load_profile(session, discovery.profile_id)
        except DiscoveryStateError as exc:
            return OperatorResult(success=False, error=str(exc))

        budget = profile.budget or {}
        analyze_top_n = int(budget.get("analyze_top_n", 25))
        skill_warnings: list[str] = []

        triage_skill = load_skill_prompt(
            session,
            skill_id=_TRIAGE_SKILL_ID,
            operator_type="discovery_analyze",
        )
        if triage_skill.warning:
            skill_warnings.append(triage_skill.warning)

        escalation_skill = load_skill_prompt(
            session,
            skill_id=_ESCALATION_SKILL_ID,
            operator_type="discovery_analyze",
        )
        if escalation_skill.warning:
            skill_warnings.append(escalation_skill.warning)

        skill_prompt = join_skill_prompts(triage_skill.prompt, escalation_skill.prompt)

        cards = list(
            session.execute(
                select(PaperCard)
                .where(PaperCard.session_id == discovery.id)
                .order_by(PaperCard.final_score.desc().nullslast())
                .limit(analyze_top_n)
            )
            .scalars()
            .all()
        )

        analyze_inputs = [
            {
                "id": str(card.id),
                "title": card.title,
                "abstract": card.abstract,
                "authors": card.authors or [],
                "venue": card.venue,
                "year": card.year,
            }
            for card in cards
        ]

        if analyze_inputs:
            router = ModelRouter()
            try:
                results = asyncio.run(
                    analyze_many(
                        router,
                        problem_statement=profile.query_text,
                        papers=analyze_inputs,
                        skill_prompt=skill_prompt,
                        concurrency=int(budget.get("analyze_concurrency", 4)),
                    )
                )
            except Exception as exc:
                log.exception("discovery_analyze.failed", error=str(exc))
                return OperatorResult(
                    success=False,
                    error=f"discovery_analyze failed: {exc}",
                )
            finally:
                with contextlib.suppress(RuntimeError):
                    # New event loop after analyze_many's close, ignore.
                    asyncio.run(router.close())
        else:
            results = []

        cards_by_id = {str(c.id): c for c in cards}
        analyzed = 0
        failed = 0
        events: list[dict] = []
        for paper_id, packet, error in results:
            card = cards_by_id.get(paper_id)
            if card is None:
                continue
            if packet is not None:
                card.metadata_analysis = packet.model_dump()
                analyzed += 1
                events.append(
                    {
                        "event_type": DiscoveryEvents.paper_metadata_analyzed.value,
                        "payload": {
                            "session_id": str(session_id),
                            "paper_id": paper_id,
                            "shortlist_fit": packet.shortlist_fit,
                            "contribution_type": packet.likely_contribution_type,
                        },
                    }
                )
            else:
                failed += 1
                card.metadata_analysis = {"error": error}

        analyze_stats = {
            "analyze_top_n": analyze_top_n,
            "candidates": len(cards),
            "analyzed": analyzed,
            "failed": failed,
            "skill_warnings": skill_warnings,
        }
        discovery.status = "analyze_complete"
        discovery.error = None
        merge_stats(discovery, {"analyze": analyze_stats})
        for warning in skill_warnings:
            append_step_log(
                discovery,
                step="analyze",
                status="warning",
                detail={"warning": warning},
            )
        append_step_log(
            discovery,
            step="analyze",
            status="ok" if failed == 0 else "partial",
            detail=analyze_stats,
        )

        enqueue_next(
            session,
            cycle_id=discovery.cycle_id,
            next_job_type="discovery_finalize",
            session_id=discovery.id,
        )
        session.commit()

    result = OperatorResult(
        success=True,
        summary=f"Metadata analysis complete: {analyzed} ok, {failed} failed",
        events=events,
    )
    return result
