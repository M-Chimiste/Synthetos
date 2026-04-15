"""hypothesis_rank operator -- computes weighted rank from scores, marks the
session completed, and transitions the cycle to portfolio_ready.
"""

from __future__ import annotations

from sqlalchemy import select

from libs.core.clock import utcnow
from libs.core.event_types import IdeationEvents
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.core.types import CycleStatus
from libs.ideation.operators._common import (
    IdeationStateError,
    append_step_log,
    hypothesis_session_id_from_payload,
    load_hypothesis_session,
    mark_failed,
    merge_stats,
)
from libs.storage.base import get_sync_session_factory
from libs.storage.models.experiment import HypothesisCard

log = get_logger("ideation.rank")

# Default score weights for ranking
_WEIGHT_NOVELTY = 0.3
_WEIGHT_FEASIBILITY = 0.4
_WEIGHT_IMPACT = 0.3


def _composite_score(card: HypothesisCard) -> float:
    """Compute weighted composite score for ranking.  Missing scores default to 0.0."""
    return (
        _WEIGHT_NOVELTY * (card.novelty_score or 0.0)
        + _WEIGHT_FEASIBILITY * (card.feasibility_score or 0.0)
        + _WEIGHT_IMPACT * (card.impact_score or 0.0)
    )


def hypothesis_rank_operator(op_input: OperatorInput) -> OperatorResult:
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

        hs.status = "ranking"
        db.flush()

        # Load candidate cards
        cards = (
            db.execute(
                select(HypothesisCard)
                .where(HypothesisCard.hypothesis_session_id == hs.id)
                .where(HypothesisCard.status == "candidate")
            )
            .scalars()
            .all()
        )

        if not cards:
            mark_failed(hs, step="rank", error="no candidate hypotheses to rank")
            db.commit()
            return OperatorResult(success=False, error="no candidate hypotheses to rank")

        # Sort by composite score descending and assign ranks
        ranked = sorted(cards, key=_composite_score, reverse=True)
        for rank_pos, card in enumerate(ranked, start=1):
            card.rank = rank_pos
            card.updated_at = utcnow()

        # Mark session complete
        hs.status = "completed"
        hs.completed_at = utcnow()

        merge_stats(hs, {"ranked_count": len(ranked)})
        append_step_log(
            hs,
            step="rank",
            detail={
                "ranked_count": len(ranked),
                "top_title": ranked[0].title if ranked else None,
                "top_score": round(_composite_score(ranked[0]), 3) if ranked else None,
            },
        )
        db.commit()

    result = OperatorResult(
        success=True,
        summary=f"Ranked {len(ranked)} hypotheses; top: {ranked[0].title if ranked else 'none'}",
        state_patch={"cycle_status": CycleStatus.portfolio_ready.value},
    )
    result.add_event(
        IdeationEvents.hypotheses_ranked.value,
        {
            "hypothesis_session_id": str(session_id),
            "ranked_count": len(ranked),
        },
    )
    result.add_event(
        IdeationEvents.session_completed.value,
        {"hypothesis_session_id": str(session_id)},
    )
    return result
