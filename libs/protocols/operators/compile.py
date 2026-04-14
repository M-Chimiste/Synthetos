"""protocol_compile operator -- compiles selected hypotheses into executable
ExperimentSpec rows, validates completeness, and transitions the cycle
to protocol_ready.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from uuid_utils import uuid7

from libs.adapters.llm.router import ModelRouter
from libs.core.clock import utcnow
from libs.core.event_types import ProtocolEvents
from libs.core.events import emit_event_sync
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.discovery.skill_support import join_skill_prompts, load_skill_prompt
from libs.protocols.validation import validate_spec
from libs.schemas.model_gateway import ModelRole
from libs.skills.lineage import record_model_call, record_skill_usage
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import ExperimentSpec, HypothesisCard, HypothesisSession
from libs.storage.models.research import ResearchCharter

log = get_logger("protocols.compile")


class _CompiledSpec(BaseModel):
    """Structured output from the protocol-drafting LLM call."""

    title: str = Field(max_length=500)
    description: str
    baseline: dict[str, Any]
    controls: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]]
    expected_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    stop_conditions: list[dict[str, Any]] = Field(default_factory=list)
    code_plan: dict[str, Any]
    base_image: str | None = None


class _SpecSet(BaseModel):
    specs: list[_CompiledSpec]


async def _compile_specs(
    hypotheses: list[dict[str, Any]],
    problem_statement: str,
    hardware_profile: dict[str, Any] | None,
    base_image: str | None,
    skill_prompt: str | None,
    variation_context: dict[str, Any] | None = None,
) -> tuple[_SpecSet, dict[str, Any]]:
    """Call the LLM to compile hypotheses into executable experiment specs."""
    router = ModelRouter()
    try:
        system_msg = (
            "You are an ML experiment protocol compiler. Given hypotheses and a "
            "research problem, produce fully executable experiment specifications. "
            "Each spec must include:\n"
            "- A baseline description with expected metrics\n"
            "- Metrics to track with direction (maximize/minimize) and optional thresholds\n"
            "- A code_plan with entry_point, dependencies, and complete file contents\n"
            "- Stop conditions\n"
            "- Expected artifacts to produce\n"
            "The code should write metrics to /artifacts/metrics.json as a flat "
            "{metric_name: numeric_value} JSON object."
        )
        system_msg = join_skill_prompts(system_msg, skill_prompt) or system_msg
        hyp_text = "\n\n".join(
            f"Hypothesis {i + 1}: {h['title']}\n"
            f"Statement: {h['statement']}\n"
            f"Rationale: {h['rationale']}\n"
            f"Scores - novelty: {h.get('novelty_score')}, "
            f"feasibility: {h.get('feasibility_score')}, "
            f"impact: {h.get('impact_score')}"
            for i, h in enumerate(hypotheses)
        )
        hw_hint = ""
        if hardware_profile:
            hw_hint = f"\nHardware profile: {hardware_profile}"
        if base_image:
            hw_hint += f"\nBase image: {base_image}"

        variation_hint = ""
        if variation_context:
            variation_hint = (
                "\n\nPrevious attempt results:\n"
                f"- Signal: {variation_context.get('signal', 'unknown')}\n"
                f"- Best frontier value: {variation_context.get('frontier_best', 'N/A')}\n"
                f"- Recommendation: {variation_context.get('recommendation_action', '')}\n"
                f"- This is variation #{variation_context.get('variation_number', 1)}.\n"
                "\nCompile a NEW experiment spec that addresses the stall/regression by "
                "varying hyperparameters, architecture choices, or training strategy. "
                "Do NOT repeat the same configuration."
            )
            prior_metrics = variation_context.get("prior_metrics")
            if prior_metrics:
                variation_hint += f"\n- Metrics achieved: {prior_metrics}"
            context_summary = variation_context.get("context_summary")
            if context_summary:
                key_findings = context_summary.get("key_findings", "")
                if key_findings:
                    variation_hint += f"\n- Loop findings: {key_findings}"
                repeated = context_summary.get("repeated_approaches", [])
                if repeated:
                    variation_hint += "\n- Repeated approaches: " + "; ".join(repeated)

        user_msg = (
            f"Problem: {problem_statement}\n\n"
            f"Hypotheses to compile:\n{hyp_text}\n"
            f"{hw_hint}\n\n"
            f"Compile each hypothesis into a complete, executable experiment spec."
            f"{variation_hint}"
        )
        result = await router.complete_structured(
            role=ModelRole.protocol_drafting,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_model=_SpecSet,
            temperature=0.3,
        )
        return result, router.get_role_config(ModelRole.protocol_drafting)
    finally:
        await router.close()


def protocol_compile_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    payload = op_input.payload

    # Protocol compile uses hypothesis_session_id or hypothesis_card_ids from payload
    hypothesis_session_id_raw = payload.get("hypothesis_session_id")
    if hypothesis_session_id_raw is None:
        return OperatorResult(success=False, error="missing hypothesis_session_id in payload")

    from uuid import UUID

    hypothesis_session_id = UUID(str(hypothesis_session_id_raw))
    hardware_profile = payload.get("hardware_profile")
    base_image = payload.get("base_image")
    explicit_card_ids = payload.get("hypothesis_card_ids")
    variation_context = payload.get("variation_context")
    from_loop = payload.get("from_loop", False)

    with factory() as db:
        hs = db.get(HypothesisSession, hypothesis_session_id)
        if hs is None:
            return OperatorResult(success=False, error="hypothesis session not found")

        charter = db.get(ResearchCharter, hs.charter_id)
        problem_statement = charter.problem_statement if charter else ""

        # Select hypotheses: explicit IDs or top-ranked
        if explicit_card_ids:
            card_uuids = [UUID(str(cid)) for cid in explicit_card_ids]
            cards = (
                db.execute(
                    select(HypothesisCard)
                    .where(HypothesisCard.id.in_(card_uuids))
                    .where(HypothesisCard.hypothesis_session_id == hypothesis_session_id)
                    .where(HypothesisCard.cycle_id == hs.cycle_id)
                    .where(HypothesisCard.charter_id == hs.charter_id)
                )
                .scalars()
                .all()
            )
            if len(cards) != len(card_uuids):
                return OperatorResult(
                    success=False,
                    error=(
                        "one or more hypothesis_card_ids are out of scope for this "
                        "hypothesis session, cycle, or charter"
                    ),
                )
        else:
            # Default: take top-5 ranked candidates or selected cards
            cards = (
                db.execute(
                    select(HypothesisCard)
                    .where(HypothesisCard.hypothesis_session_id == hypothesis_session_id)
                    .where(HypothesisCard.status.in_(["candidate", "selected"]))
                    .order_by(HypothesisCard.rank.asc().nulls_last())
                    .limit(5)
                )
                .scalars()
                .all()
            )

        if not cards:
            return OperatorResult(success=False, error="no hypotheses available to compile")

        # Mark selected
        for card in cards:
            if card.status == "candidate":
                card.status = "selected"
                card.updated_at = utcnow()

        hypotheses_for_llm = [
            {
                "title": c.title,
                "statement": c.statement,
                "rationale": c.rationale,
                "novelty_score": c.novelty_score,
                "feasibility_score": c.feasibility_score,
                "impact_score": c.impact_score,
            }
            for c in cards
        ]

        planning_skill = load_skill_prompt(
            db,
            skill_id="ideation.experiment_planning",
            operator_type=op_input.job_type,
        )
        coding_skill = load_skill_prompt(
            db,
            skill_id="coding.experiment_coding",
            operator_type=op_input.job_type,
        )
        combined_skill_prompt = join_skill_prompts(planning_skill.prompt, coding_skill.prompt)
        if planning_skill.prompt:
            record_skill_usage(
                db,
                skill_id="ideation.experiment_planning",
                cycle_id=hs.cycle_id,
                operator_type=op_input.job_type,
                job_id=op_input.job_id,
            )
        if coding_skill.prompt:
            record_skill_usage(
                db,
                skill_id="coding.experiment_coding",
                cycle_id=hs.cycle_id,
                operator_type=op_input.job_type,
                job_id=op_input.job_id,
            )

        # Call LLM
        try:
            spec_set, role_cfg = asyncio.run(
                _compile_specs(
                    hypotheses_for_llm,
                    problem_statement,
                    hardware_profile,
                    base_image,
                    combined_skill_prompt,
                    variation_context=variation_context,
                )
            )
        except Exception as exc:
            return OperatorResult(success=False, error=f"protocol compilation failed: {exc}")
        record_model_call(
            db,
            cycle_id=hs.cycle_id,
            job_id=op_input.job_id,
            role=ModelRole.protocol_drafting.value,
            provider=str(role_cfg.get("provider", "unknown")),
            model_id=str(role_cfg.get("model", "unknown")),
        )

        # Validate and persist specs
        compiled_ids = []
        rejected_count = 0

        for card, compiled in zip(cards, spec_set.specs, strict=False):
            spec_data = compiled.model_dump()
            validation = validate_spec(spec_data)

            spec = ExperimentSpec(
                id=uuid7(),
                hypothesis_card_id=card.id,
                charter_id=hs.charter_id,
                cycle_id=hs.cycle_id,
                title=compiled.title,
                description=compiled.description,
                baseline=compiled.baseline,
                controls=compiled.controls,
                metrics=compiled.metrics,
                expected_artifacts=compiled.expected_artifacts,
                stop_conditions=compiled.stop_conditions,
                code_plan=compiled.code_plan,
                hardware_profile=hardware_profile,
                base_image=compiled.base_image or base_image,
                build_recipe=None,
                created_at=utcnow(),
                updated_at=utcnow(),
            )

            if validation.valid:
                spec.status = "validated"
                card.status = "compiled"
                compiled_ids.append(spec.id)
                emit_event_sync(
                    db,
                    event_type=ProtocolEvents.spec_compiled.value,
                    charter_id=hs.charter_id,
                    cycle_id=hs.cycle_id,
                    payload={
                        "spec_id": str(spec.id),
                        "hypothesis_card_id": str(card.id),
                        "title": spec.title,
                    },
                )
            else:
                spec.status = "rejected"
                spec.rejection_reason = "; ".join(validation.errors)
                rejected_count += 1
                emit_event_sync(
                    db,
                    event_type=ProtocolEvents.spec_rejected.value,
                    charter_id=hs.charter_id,
                    cycle_id=hs.cycle_id,
                    payload={
                        "spec_id": str(spec.id),
                        "hypothesis_card_id": str(card.id),
                        "errors": validation.errors,
                    },
                )

            card.updated_at = utcnow()
            db.add(spec)

        emit_event_sync(
            db,
            event_type=ProtocolEvents.compilation_completed.value,
            charter_id=hs.charter_id,
            cycle_id=hs.cycle_id,
            payload={
                "compiled_count": len(compiled_ids),
                "rejected_count": rejected_count,
            },
        )
        db.commit()

    if not compiled_ids:
        return OperatorResult(
            success=False,
            error=f"all {rejected_count} specs were rejected as under-specified",
        )

    # Phase 5: when invoked from the autonomous loop, create a RunRecord
    # and enqueue execution_setup directly instead of transitioning state.
    if from_loop:
        from libs.execution.operators._common import enqueue_next

        first_spec_id = compiled_ids[0]
        with factory() as db:
            from libs.storage.models.experiment import RunRecord

            spec_row = db.get(ExperimentSpec, first_spec_id)
            if spec_row is None:
                return OperatorResult(success=False, error="compiled spec not found")

            # Count existing runs for this spec to determine run_number
            from sqlalchemy import func as sa_func

            max_run_num = db.execute(
                select(sa_func.coalesce(sa_func.max(RunRecord.run_number), 0))
                .where(RunRecord.experiment_spec_id == first_spec_id)
            ).scalar_one()

            new_run = RunRecord(
                id=uuid7(),
                experiment_spec_id=first_spec_id,
                charter_id=spec_row.charter_id,
                cycle_id=spec_row.cycle_id,
                run_number=max_run_num + 1,
                status="pending",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(new_run)
            enqueue_next(
                db,
                cycle_id=spec_row.cycle_id,
                next_job_type="execution_setup",
                run_record_id=new_run.id,
            )
            db.commit()

        return OperatorResult(
            success=True,
            summary=(
                f"Compiled {len(compiled_ids)} specs from loop "
                f"({rejected_count} rejected); enqueued execution_setup"
            ),
        )

    result = OperatorResult(
        success=True,
        summary=(
            f"Compiled {len(compiled_ids)} specs "
            f"({rejected_count} rejected); cycle -> protocol_ready"
        ),
        state_patch={"cycle_status": CycleStatus.protocol_ready.value},
    )
    result.add_event(
        ProtocolEvents.compilation_completed.value,
        {
            "compiled_count": len(compiled_ids),
            "rejected_count": rejected_count,
        },
    )
    return result
