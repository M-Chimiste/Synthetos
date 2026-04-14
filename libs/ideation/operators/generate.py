"""hypothesis_generate operator -- loads evidence cards for the cycle, calls the
hypothesis_generation model role, and creates HypothesisCard rows.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from uuid_utils import uuid7

from libs.adapters.llm.router import ModelRouter
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
    mark_started_if_needed,
    merge_stats,
)
from libs.patterns.embedding import embed_text
from libs.patterns.injection import InjectionPolicy, inject_patterns
from libs.schemas.model_gateway import ModelRole
from libs.skills.lineage import record_model_call, record_skill_usage
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import HypothesisCard
from libs.storage.models.research import ResearchCharter, ResearchCycle

log = get_logger("ideation.generate")


class _GeneratedHypothesis(BaseModel):
    title: str = Field(max_length=500)
    statement: str
    rationale: str
    mechanism: str | None = None
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class _HypothesisSet(BaseModel):
    hypotheses: list[_GeneratedHypothesis]


async def _generate_hypotheses(
    charter_title: str,
    problem_statement: str,
    evidence_summaries: list[dict[str, Any]],
    max_hypotheses: int,
    skill_prompt: str | None,
    pattern_hints: list[dict[str, Any]] | None = None,
) -> tuple[_HypothesisSet, dict[str, Any]]:
    """Call the LLM to generate candidate hypotheses from evidence."""
    router = ModelRouter()
    try:
        system_msg = (
            "You are a research hypothesis generator. Given a research problem and "
            "supporting evidence, generate novel, testable hypotheses. Each hypothesis "
            "should be grounded in the evidence and include a clear rationale. "
            f"Generate up to {max_hypotheses} hypotheses."
        )
        system_msg = join_skill_prompts(system_msg, skill_prompt) or system_msg
        evidence_text = "\n\n".join(
            f"Evidence [{e['id']}]: {e['claim']} (type: {e['type']}, confidence: {e['confidence']})"
            for e in evidence_summaries
        )
        pattern_text = ""
        if pattern_hints:
            hint_lines = []
            for hint in pattern_hints:
                hint_lines.append(
                    f"- [{hint['pattern_type']}] {hint['title']} "
                    f"(conf={hint['effective_confidence']}): {hint['summary']}"
                )
            pattern_text = (
                "\nPrior-cycle patterns to consider (from this system's memory):\n"
                + "\n".join(hint_lines)
                + "\n"
            )
        user_msg = (
            f"Research problem: {charter_title}\n"
            f"Problem statement: {problem_statement}\n\n"
            f"Available evidence:\n{evidence_text}\n"
            f"{pattern_text}\n"
            f"Generate up to {max_hypotheses} testable hypotheses based on this evidence. "
            "For each hypothesis, reference the evidence IDs that support it."
        )
        result = await router.complete_structured(
            role=ModelRole.hypothesis_generation,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_model=_HypothesisSet,
            temperature=0.7,
        )
        return result, router.get_role_config(ModelRole.hypothesis_generation)
    finally:
        await router.close()


def hypothesis_generate_operator(op_input: OperatorInput) -> OperatorResult:
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

        mark_started_if_needed(hs)
        hs.status = "generating"
        hs.error = None
        db.flush()

        # Load charter for context
        charter = db.get(ResearchCharter, hs.charter_id)
        if charter is None:
            mark_failed(hs, step="generate", error="charter not found")
            db.commit()
            return OperatorResult(success=False, error="charter not found")

        # Load evidence cards for this cycle
        from libs.storage.models.analysis import EvidenceCard

        evidence_rows = db.execute(
            select(EvidenceCard).where(EvidenceCard.cycle_id == hs.cycle_id)
        ).scalars().all()

        if not evidence_rows:
            mark_failed(hs, step="generate", error="no evidence cards found for cycle")
            db.commit()
            return OperatorResult(success=False, error="no evidence cards found for cycle")

        evidence_summaries = [
            {
                "id": str(e.id),
                "claim": e.claim,
                "type": e.evidence_type,
                "confidence": e.confidence,
            }
            for e in evidence_rows
        ]

        budget = dict(hs.budget or {})
        max_hypotheses = int(budget.get("max_hypotheses", 10))

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
            )

        # Phase 6: inject canonical patterns into hypothesis generation context.
        cycle = db.get(ResearchCycle, hs.cycle_id)
        policy = InjectionPolicy.from_cycle_config(cycle.config if cycle else None)
        pattern_matches = inject_patterns(
            db,
            charter_id=hs.charter_id,
            current_cycle_id=hs.cycle_id,
            types=["successful_line", "failure"],
            policy=policy,
            problem_profile_embedding=embed_text(
                "\n".join(
                    [
                        charter.title,
                        charter.problem_statement,
                        " ".join(item["summary"] for item in evidence_summaries),
                    ]
                )
            ),
            operator_name="hypothesis_generate",
        )
        pattern_hints = [m.to_context() for m in pattern_matches]

        # Call LLM
        try:
            hypothesis_set, role_cfg = asyncio.run(
                _generate_hypotheses(
                    charter_title=charter.title,
                    problem_statement=charter.problem_statement,
                    evidence_summaries=evidence_summaries,
                    max_hypotheses=max_hypotheses,
                    skill_prompt=skill_result.prompt,
                    pattern_hints=pattern_hints,
                )
            )
        except Exception as exc:
            mark_failed(hs, step="generate", error=str(exc))
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

        # Persist hypothesis cards
        created_ids: list[UUID] = []
        for h in hypothesis_set.hypotheses[:max_hypotheses]:
            card_id = uuid7()
            card = HypothesisCard(
                id=card_id,
                hypothesis_session_id=hs.id,
                charter_id=hs.charter_id,
                cycle_id=hs.cycle_id,
                title=h.title,
                statement=h.statement,
                rationale=h.rationale,
                mechanism=h.mechanism,
                supporting_evidence_ids=h.supporting_evidence_ids,
                status="candidate",
            )
            db.add(card)
            created_ids.append(UUID(str(card_id)))

        merge_stats(hs, {"generated_count": len(created_ids)})
        append_step_log(
            hs,
            step="generate",
            detail={
                "evidence_count": len(evidence_summaries),
                "generated_count": len(created_ids),
            },
        )

        next_job_id = enqueue_next(
            db,
            cycle_id=hs.cycle_id,
            next_job_type="hypothesis_critique",
            hypothesis_session_id=hs.id,
        )
        db.commit()

    result = OperatorResult(
        success=True,
        summary=f"Generated {len(created_ids)} hypotheses; enqueued hypothesis_critique",
    )
    result.add_event(
        IdeationEvents.hypotheses_generated.value,
        {
            "hypothesis_session_id": str(session_id),
            "generated_count": len(created_ids),
            "next_job_id": str(next_job_id),
        },
    )
    return result
