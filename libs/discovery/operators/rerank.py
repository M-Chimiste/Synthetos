"""discovery_rerank operator -- runs the cross-encoder reranker (or fallback)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from libs.adapters.reranker.base import RerankDoc
from libs.core.event_types import DiscoveryEvents
from libs.core.logging import get_logger
from libs.core.operators import OperatorInput, OperatorResult
from libs.discovery.operators._common import (
    DiscoveryStateError,
    append_step_log,
    enqueue_next,
    load_profile,
    load_session,
    merge_stats,
    session_id_from_payload,
)
from libs.discovery.rerank_strategy import run_rerank
from libs.storage.base import get_sync_session_factory
from libs.storage.models.papers import PaperCard

log = get_logger(__name__)


def _build_doc_text(card: PaperCard) -> str:
    title = card.title or ""
    abstract = card.abstract or ""
    return f"{title}\n\n{abstract}".strip()


def discovery_rerank_operator(op_input: OperatorInput) -> OperatorResult:
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

        cards = list(
            session.execute(
                select(PaperCard)
                .where(PaperCard.session_id == discovery.id)
                .order_by(PaperCard.first_stage_score.desc().nullslast())
            )
            .scalars()
            .all()
        )

        rerank_policy = profile.rerank_policy or {}
        enabled = bool(rerank_policy.get("enabled", True))
        top_n = int(rerank_policy.get("top_n", 100))
        budget_seconds = float(rerank_policy.get("budget_seconds", 30.0))
        model_name = rerank_policy.get("model")

        # Snapshot first-stage final_score for cards we won't rerank, so the
        # downstream operators have *something* to sort on.
        for card in cards:
            if card.final_score is None:
                card.final_score = card.first_stage_score

        rerank_pool = cards[:top_n]
        docs = [
            RerankDoc(
                id=str(card.id),
                text=_build_doc_text(card),
                first_stage_score=card.first_stage_score,
            )
            for card in rerank_pool
        ]

        from libs.discovery.rerank_strategy import build_default_reranker

        primary = build_default_reranker(model_name) if enabled else None

        try:
            outcome = asyncio.run(
                run_rerank(
                    query=profile.query_text,
                    docs=docs,
                    enabled=enabled,
                    top_k=top_n,
                    budget_seconds=budget_seconds,
                    primary=primary,
                )
            )
        except Exception as exc:
            log.exception("discovery_rerank.unexpected_error", error=str(exc))
            return OperatorResult(success=False, error=f"discovery_rerank failed: {exc}")

        # Apply rerank scores back to the cards.
        score_map = {res.id: res.rerank_score for res in outcome.results}
        for card in rerank_pool:
            score = score_map.get(str(card.id))
            if score is not None:
                card.rerank_score = score
                card.final_score = score

        discovery.status = "rerank_complete"
        rerank_stats = {
            "candidates": len(cards),
            "rerank_pool": len(rerank_pool),
            "used_reranker": outcome.used_reranker,
            "fallback_reason": outcome.fallback_reason,
        }
        merge_stats(discovery, {"rerank": rerank_stats})
        append_step_log(
            discovery,
            step="rerank",
            status="ok",
            detail=rerank_stats,
        )

        enqueue_next(
            session,
            cycle_id=discovery.cycle_id,
            next_job_type="discovery_analyze",
            session_id=discovery.id,
        )
        session.commit()

    result = OperatorResult(
        success=True,
        summary=(
            f"Rerank complete via {outcome.used_reranker}"
            + (f" ({outcome.fallback_reason})" if outcome.fallback_reason else "")
        ),
    )
    if outcome.fallback_reason is not None:
        result.add_event(
            DiscoveryEvents.rerank_skipped.value,
            {
                "session_id": str(session_id),
                "used_reranker": outcome.used_reranker,
                "reason": outcome.fallback_reason,
            },
        )
    else:
        result.add_event(
            DiscoveryEvents.rerank_completed.value,
            {
                "session_id": str(session_id),
                "used_reranker": outcome.used_reranker,
                "rerank_pool": len(rerank_pool),
            },
        )
    return result
