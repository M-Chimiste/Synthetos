"""discovery_finalize operator -- builds Stable + Discovery views, writes the
report bundle to disk, and transitions the cycle to ``discovery_screened``.
"""

from __future__ import annotations

from sqlalchemy import select

from libs.core.clock import utcnow
from libs.core.config import get_settings
from libs.core.event_types import DiscoveryEvents
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.discovery.operators._common import (
    DiscoveryStateError,
    append_step_log,
    load_profile,
    load_session,
    mark_failed,
    merge_stats,
    session_id_from_payload,
)
from libs.discovery.reports import (
    build_report_paths,
    render_json,
    render_markdown,
    write_report_bundle,
)
from libs.discovery.skill_support import (
    join_skill_prompts,
    load_skill_prompt,
    run_shortlist_critique,
)
from libs.discovery.views import build_discovery_view, build_stable_view
from libs.storage.base import get_sync_session_factory
from libs.storage.models.papers import PaperCard

log = get_logger(__name__)


_DEFAULT_STABLE_TOP_K = 25
_DEFAULT_DISCOVERY_TOP_K = 25
_DEFAULT_MMR_LAMBDA = 0.7
_SHORTLIST_CRITIQUE_SKILL_ID = "literature.shortlist_critique"
_ESCALATION_SKILL_ID = "literature.escalation_rationale"


def discovery_finalize_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    settings = get_settings()
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

        cards = list(
            session.execute(
                select(PaperCard)
                .where(PaperCard.session_id == discovery.id)
                .order_by(PaperCard.final_score.desc().nullslast())
            )
            .scalars()
            .all()
        )

        budget = profile.budget or {}
        stable_top_k = int(budget.get("stable_top_k", _DEFAULT_STABLE_TOP_K))
        discovery_top_k = int(budget.get("discovery_top_k", _DEFAULT_DISCOVERY_TOP_K))
        mmr_lambda = float(budget.get("discovery_mmr_lambda", _DEFAULT_MMR_LAMBDA))

        view_pref = profile.view_preference or "both"

        stable_view: list[PaperCard] = []
        discovery_view: list[PaperCard] = []
        if view_pref in ("stable", "both"):
            stable_view = build_stable_view(cards, top_k=stable_top_k)
        if view_pref in ("discovery", "both"):
            discovery_view = build_discovery_view(
                cards,
                top_k=discovery_top_k,
                lambda_param=mmr_lambda,
            )

        stable_ids = {c.id for c in stable_view}
        discovery_ids = {c.id for c in discovery_view}
        for card in cards:
            membership: list[str] = []
            if card.id in stable_ids:
                membership.append("stable")
            if card.id in discovery_ids:
                membership.append("discovery")
            card.view_membership = membership or None
            if membership and card.triage_status == "discovered":
                card.triage_status = "shortlisted"

        included_cards = [c for c in cards if c.view_membership]

        stats = dict(discovery.stats or {})
        finalize_stats = {
            "total_cards": len(cards),
            "stable_view_size": len(stable_view),
            "discovery_view_size": len(discovery_view),
            "shortlisted": len(included_cards),
        }
        stats["finalize"] = finalize_stats

        skill_warnings: list[str] = []
        shortlist_skill = load_skill_prompt(
            session,
            skill_id=_SHORTLIST_CRITIQUE_SKILL_ID,
            operator_type="discovery_finalize",
        )
        if shortlist_skill.warning:
            skill_warnings.append(shortlist_skill.warning)

        escalation_skill = load_skill_prompt(
            session,
            skill_id=_ESCALATION_SKILL_ID,
            operator_type="discovery_finalize",
        )
        if escalation_skill.warning:
            skill_warnings.append(escalation_skill.warning)

        critique_prompt = join_skill_prompts(shortlist_skill.prompt, escalation_skill.prompt)
        if critique_prompt:
            try:
                critique = run_shortlist_critique(
                    problem_statement=profile.query_text,
                    stable_view=stable_view,
                    discovery_view=discovery_view,
                    skill_prompt=critique_prompt,
                )
                stats["shortlist_critique"] = critique.model_dump()
            except Exception as exc:
                warning = f"shortlist critique skill failed: {exc}"
                skill_warnings.append(warning)

        if skill_warnings:
            stats["finalize_skill_warnings"] = skill_warnings

        # Write the report bundle to disk.
        paths = build_report_paths(settings.data_root, discovery.id)
        markdown_doc = render_markdown(
            session=discovery,
            profile=profile,
            stable_view=stable_view,
            discovery_view=discovery_view,
            stats=stats,
        )
        json_payload = render_json(
            session=discovery,
            profile=profile,
            stable_view=stable_view,
            discovery_view=discovery_view,
            stats=stats,
        )
        try:
            write_report_bundle(
                paths,
                markdown=markdown_doc,
                json_payload=json_payload,
                cards=included_cards,
            )
            report_path = str(paths.markdown)
        except Exception as exc:
            error = f"discovery_finalize report write failed: {exc}"
            log.exception("discovery_finalize.report_write_failed", error=str(exc))
            mark_failed(
                discovery,
                step="finalize",
                error=error,
                detail={
                    "report_path": None,
                    **finalize_stats,
                },
            )
            failure_stats: dict[str, object] = {"finalize": finalize_stats}
            if "shortlist_critique" in stats:
                failure_stats["shortlist_critique"] = stats["shortlist_critique"]
            if skill_warnings:
                failure_stats["finalize_skill_warnings"] = skill_warnings
            merge_stats(discovery, failure_stats)
            session.commit()
            result = OperatorResult(
                success=False,
                error=error,
            )
            result.add_event(
                DiscoveryEvents.session_failed.value,
                {
                    "session_id": str(session_id),
                    "operator": "discovery_finalize",
                    "error": error,
                },
            )
            return result

        discovery.status = "completed"
        discovery.completed_at = utcnow()
        discovery.report_artifact_path = report_path
        discovery.error = None
        success_stats: dict[str, object] = {"finalize": finalize_stats}
        if "shortlist_critique" in stats:
            success_stats["shortlist_critique"] = stats["shortlist_critique"]
        if skill_warnings:
            success_stats["finalize_skill_warnings"] = skill_warnings
        merge_stats(discovery, success_stats)
        for warning in skill_warnings:
            append_step_log(
                discovery,
                step="finalize",
                status="warning",
                detail={"warning": warning},
            )
        append_step_log(
            discovery,
            step="finalize",
            status="ok",
            detail={
                "report_path": report_path,
                **finalize_stats,
            },
        )

        session.commit()

    result = OperatorResult(
        success=True,
        summary=(
            f"Finalize complete; stable={finalize_stats['stable_view_size']} "
            f"discovery={finalize_stats['discovery_view_size']}"
        ),
        state_patch={"cycle_status": CycleStatus.discovery_screened.value},
    )
    if report_path:
        result.artifacts.append(report_path)
    result.add_event(
        DiscoveryEvents.view_built.value,
        {
            "session_id": str(session_id),
            "stable": finalize_stats["stable_view_size"],
            "discovery": finalize_stats["discovery_view_size"],
        },
    )
    result.add_event(
        DiscoveryEvents.session_finalized.value,
        {
            "session_id": str(session_id),
            "report_path": report_path,
            "stats": finalize_stats,
        },
    )
    return result
