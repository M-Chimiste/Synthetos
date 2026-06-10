"""hypothesis_critique operator -- critiques candidate hypotheses and assigns
novelty, feasibility, and impact scores.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from libs.adapters.llm.router import ModelRouter
from libs.core.clock import utcnow
from libs.core.event_types import IdeationEvents
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.discovery.skill_support import join_skill_prompts, load_skill_prompt
from libs.ideation.operators._common import (
    IdeationStateError,
    append_step_log,
    enqueue_next,
    hypothesis_session_id_from_payload,
    load_hypothesis_session,
    mark_failed,
    merge_stats,
)
from libs.prompts import render_prompt
from libs.schemas.model_gateway import ModelRole
from libs.skills.lineage import record_model_call, record_skill_usage
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import HypothesisCard

log = get_logger("ideation.critique")


class _CritiqueResult(BaseModel):
    # 1-based index matching "Hypothesis N" in the input: explicit alignment
    # instead of relying on output order (small models reorder/skip items).
    hypothesis_index: int = Field(ge=1)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    novelty_score: float = Field(ge=0.0, le=1.0)
    feasibility_score: float = Field(ge=0.0, le=1.0)
    impact_score: float = Field(ge=0.0, le=1.0)


class _CritiqueSet(BaseModel):
    critiques: list[_CritiqueResult]


async def _critique_hypotheses(
    hypotheses: list[dict[str, Any]],
    problem_statement: str,
    skill_prompt: str | None,
) -> tuple[_CritiqueSet, dict[str, Any]]:
    """Call the LLM to critique a batch of hypotheses."""
    router = ModelRouter()
    try:
        system_msg = render_prompt("ideation.hypothesis_critique")
        system_msg = join_skill_prompts(system_msg, skill_prompt) or system_msg
        hypotheses_text = "\n\n".join(
            f"Hypothesis {i + 1}: {h['title']}\n"
            f"Statement: {h['statement']}\n"
            f"Rationale: {h['rationale']}"
            for i, h in enumerate(hypotheses)
        )
        user_msg = (
            f"Problem context: {problem_statement}\n\n"
            f"Hypotheses to critique:\n{hypotheses_text}\n\n"
            f"Provide a critique for each of the {len(hypotheses)} hypotheses, in order."
        )
        result = await router.complete_structured(
            role=ModelRole.hypothesis_generation,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_model=_CritiqueSet,
            temperature=0.5,
        )
        return result, router.get_role_config(ModelRole.hypothesis_generation)
    finally:
        await router.close()


def hypothesis_critique_operator(op_input: OperatorInput) -> OperatorResult:
    factory = get_sync_session_factory()
    try:
        session_id = hypothesis_session_id_from_payload(op_input)
    except IdeationStateError as exc:
        return OperatorResult(success=False, error=str(exc))

    with factory() as db:
        try:
            hs = load_hypothesis_session(db, session_id)
        except IdeationStateError as exc:
            return OperatorResult(success=False, error=str(exc))

        hs.status = "critiquing"
        db.flush()

        # Load charter for problem context
        from libs.storage.models.research import ResearchCharter

        charter = db.get(ResearchCharter, hs.charter_id)
        problem_statement = charter.problem_statement if charter else ""

        # Load candidate cards
        cards = (
            db.execute(
                select(HypothesisCard)
                .where(HypothesisCard.hypothesis_session_id == hs.id)
                .where(HypothesisCard.status == "candidate")
                .order_by(HypothesisCard.created_at)
            )
            .scalars()
            .all()
        )

        if not cards:
            mark_failed(hs, step="critique", error="no candidate hypotheses to critique")
            db.commit()
            return OperatorResult(success=False, error="no candidate hypotheses to critique")

        hypotheses_for_llm = [
            {
                "title": c.title,
                "statement": c.statement,
                "rationale": c.rationale,
            }
            for c in cards
        ]

        skill_result = load_skill_prompt(
            db,
            skill_id="ideation.hypothesis_generation",
            operator_type=op_input.job_type,
        )
        if skill_result.prompt:
            record_skill_usage(
                db,
                skill_id="ideation.hypothesis_generation",
                cycle_id=hs.cycle_id,
                operator_type=op_input.job_type,
                job_id=op_input.job_id,
                config={"mode": "critique"},
            )

        try:
            critique_set, role_cfg = asyncio.run(
                _critique_hypotheses(
                    hypotheses_for_llm,
                    problem_statement,
                    skill_result.prompt,
                )
            )
        except Exception as exc:
            mark_failed(hs, step="critique", error=str(exc))
            db.commit()
            return OperatorResult(success=False, error=str(exc))
        record_model_call(
            db,
            cycle_id=hs.cycle_id,
            job_id=op_input.job_id,
            role=ModelRole.hypothesis_generation.value,
            provider=str(role_cfg.get("provider", "unknown")),
            model_id=str(role_cfg.get("model", "unknown")),
        )

        # Apply critiques to cards, matched by explicit hypothesis_index
        # (the model may return them out of order or drop one).
        critiqued_count = 0
        by_index = {c.hypothesis_index: c for c in critique_set.critiques}
        for i, card in enumerate(cards, start=1):
            critique = by_index.get(i)
            if critique is None:
                log.warning(
                    "critique_missing_for_hypothesis",
                    hypothesis_index=i,
                    card_id=str(card.id),
                )
                continue
            card.critique = {
                "strengths": critique.strengths,
                "weaknesses": critique.weaknesses,
                "failure_modes": critique.failure_modes,
            }
            card.novelty_score = critique.novelty_score
            card.feasibility_score = critique.feasibility_score
            card.impact_score = critique.impact_score
            card.updated_at = utcnow()
            critiqued_count += 1

        merge_stats(hs, {"critiqued_count": critiqued_count})
        append_step_log(hs, step="critique", detail={"critiqued_count": critiqued_count})

        next_job_id = enqueue_next(
            db,
            cycle_id=hs.cycle_id,
            next_job_type="hypothesis_rank",
            hypothesis_session_id=hs.id,
        )
        db.commit()

    result = OperatorResult(
        success=True,
        summary=f"Critiqued {critiqued_count} hypotheses; enqueued hypothesis_rank",
    )
    result.add_event(
        IdeationEvents.hypotheses_critiqued.value,
        {
            "hypothesis_session_id": str(session_id),
            "critiqued_count": critiqued_count,
            "next_job_id": str(next_job_id),
        },
    )
    return result
