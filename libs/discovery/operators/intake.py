"""discovery_intake operator -- normalizes the problem profile, marks the
session started, transitions the cycle to ``discovery_ready``, and enqueues
the next operator (``discovery_search``).
"""

from __future__ import annotations

from libs.core.event_types import DiscoveryEvents
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.discovery.operators._common import (
    DiscoveryStateError,
    append_step_log,
    enqueue_next,
    load_profile,
    load_session,
    mark_started_if_needed,
    merge_stats,
    session_id_from_payload,
)
from libs.discovery.skill_support import load_skill_prompt, run_problem_scoping
from libs.storage.base import get_sync_session_factory

_PROBLEM_SCOPING_SKILL_ID = "literature.problem_scoping"


def discovery_intake_operator(op_input: OperatorInput) -> OperatorResult:
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

        mark_started_if_needed(discovery)
        discovery.status = "intake_complete"
        discovery.error = None

        scoped_artifact: dict[str, object] | None = None
        skill = load_skill_prompt(
            session,
            skill_id=_PROBLEM_SCOPING_SKILL_ID,
            operator_type="discovery_intake",
        )
        if skill.warning:
            append_step_log(
                discovery,
                step="intake",
                status="warning",
                detail={
                    "skill_id": _PROBLEM_SCOPING_SKILL_ID,
                    "warning": skill.warning,
                },
            )
        elif skill.prompt:
            try:
                packet = run_problem_scoping(
                    query_text=profile.query_text,
                    notes=profile.notes,
                    skill_prompt=skill.prompt,
                )
                source_scope = dict(profile.source_scope or {})
                scoped_artifact = {
                    "derived_query": packet.dense_query,
                    "synonyms": packet.synonyms,
                    "categories": packet.categories,
                    "exclusions": packet.exclusions,
                    "skill_id": _PROBLEM_SCOPING_SKILL_ID,
                }
                source_scope["search_hints"] = scoped_artifact
                profile.source_scope = source_scope
            except Exception as exc:
                append_step_log(
                    discovery,
                    step="intake",
                    status="warning",
                    detail={
                        "skill_id": _PROBLEM_SCOPING_SKILL_ID,
                        "warning": f"problem scoping skill failed: {exc}",
                    },
                )

        merge_stats(
            discovery,
            {
                "view_preference": profile.view_preference,
                "source_scope": profile.source_scope,
                "scoped_query": scoped_artifact,
            },
        )
        append_step_log(
            discovery,
            step="intake",
            status="ok",
            detail={
                "query_text_chars": len(profile.query_text),
                "view_preference": profile.view_preference,
                "scoped_query": scoped_artifact,
            },
        )

        next_job_id = enqueue_next(
            session,
            cycle_id=discovery.cycle_id,
            next_job_type="discovery_search",
            session_id=discovery.id,
        )
        session.commit()

    result = OperatorResult(
        success=True,
        summary=f"Intake complete; enqueued discovery_search job {next_job_id}",
        state_patch={"cycle_status": CycleStatus.discovery_ready.value},
    )
    result.add_event(
        DiscoveryEvents.intake_completed.value,
        {
            "session_id": str(session_id),
            "next_job_id": str(next_job_id),
        },
    )
    return result
