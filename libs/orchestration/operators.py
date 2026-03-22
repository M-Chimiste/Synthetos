from __future__ import annotations

from libs.core.config import AppConfig
from libs.core.operators import (
    ContextPack,
    OperatorContext,
    OperatorReport,
    OperatorResult,
    SkillExecutionOutcome,
    StatePatch,
)
from libs.core.policy import Actor
from libs.core.state_machine import CycleStatus
from libs.storage.models import (
    JobModel,
    ResearchCharterModel,
    ResearchCycleModel,
    SkillVersionModel,
)
from libs.storage.services import bind_skills_for_cycle


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


OPERATOR_REGISTRY = {
    "initialize_cycle": initialize_cycle_operator,
}
