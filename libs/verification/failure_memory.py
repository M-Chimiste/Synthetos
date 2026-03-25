"""Failure-memory aggregation helpers for same-charter feedback loops."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from libs.storage.models import (
    ExperimentSpecModel,
    FailurePostmortemModel,
    ResearchCycleModel,
    RunRecordModel,
)

if TYPE_CHECKING:
    from libs.memory.retrieval import PatternRetrievalService


def _normalize_label(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def aggregate_failure_guidance(
    session: Session,
    *,
    charter_id: int,
) -> dict[str, list[dict[str, Any]]]:
    """Aggregate same-charter failure hints into retrieval/protocol/ranking guidance."""
    postmortems = session.scalars(
        select(FailurePostmortemModel)
        .join(ResearchCycleModel, FailurePostmortemModel.cycle_id == ResearchCycleModel.id)
        .join(RunRecordModel, FailurePostmortemModel.run_record_id == RunRecordModel.id)
        .where(ResearchCycleModel.charter_id == charter_id)
        .order_by(FailurePostmortemModel.created_at.desc())
    ).all()

    retrieval_guidance: list[dict[str, Any]] = []
    protocol_guidance: list[dict[str, Any]] = []
    failure_counts = Counter(pm.failure_class for pm in postmortems)
    ranking_caution_signals = [
        {
            "failure_class": failure_class,
            "repeat_count": repeat_count,
            "detail": (
                f"Same-charter failure class '{failure_class}' "
                f"occurred {repeat_count} times."
            ),
        }
        for failure_class, repeat_count in failure_counts.items()
        if repeat_count >= 2
    ]

    seen_queries: set[str] = set()
    seen_fields: set[str] = set()
    for pm in postmortems:
        for hint in pm.retrieval_hints or []:
            query = str(hint.get("query", "")).strip()
            if query and query not in seen_queries:
                seen_queries.add(query)
                retrieval_guidance.append({
                    "query": query,
                    "rationale": hint.get("rationale", pm.root_cause_summary),
                    "source_postmortem_public_id": pm.public_id,
                })
        for hint in pm.protocol_update_hints or []:
            field = str(hint.get("field", "")).strip()
            key = f"{field}:{hint.get('suggestion', '')}"
            if field and key not in seen_fields:
                seen_fields.add(key)
                protocol_guidance.append({
                    "field": field,
                    "suggestion": hint.get("suggestion", ""),
                    "source_postmortem_public_id": pm.public_id,
                })

    return {
        "retrieval_guidance": retrieval_guidance,
        "protocol_guidance": protocol_guidance,
        "ranking_caution_signals": ranking_caution_signals,
    }


def get_hypothesis_failure_caution(
    session: Session,
    *,
    charter_id: int,
    hypothesis_title: str,
) -> dict[str, Any] | None:
    """Return a bounded ranking penalty for repeated same-charter hypothesis failures."""
    normalized_title = _normalize_label(hypothesis_title)
    if not normalized_title:
        return None

    rows = session.execute(
        select(FailurePostmortemModel, ExperimentSpecModel)
        .join(RunRecordModel, FailurePostmortemModel.run_record_id == RunRecordModel.id)
        .join(ExperimentSpecModel, RunRecordModel.experiment_spec_id == ExperimentSpecModel.id)
        .join(ResearchCycleModel, FailurePostmortemModel.cycle_id == ResearchCycleModel.id)
        .where(ResearchCycleModel.charter_id == charter_id)
        .order_by(FailurePostmortemModel.created_at.desc())
    ).all()

    matching_postmortems = [
        pm
        for pm, spec in rows
        if _normalize_label(spec.title) == normalized_title
    ]
    repeat_count = len(matching_postmortems)
    if repeat_count < 2:
        return None

    penalty = min(0.2, 0.05 * repeat_count)
    failure_classes = sorted({pm.failure_class for pm in matching_postmortems})
    return {
        "penalty": penalty,
        "repeat_count": repeat_count,
        "failure_classes": failure_classes,
        "detail": (
            f"Applied a {penalty:.2f} portfolio penalty because this same-charter "
            f"lineage has {repeat_count} prior failures ({', '.join(failure_classes)})."
        ),
    }


# ---------------------------------------------------------------------------
# Phase D — Cross-charter pattern-aware guidance
# ---------------------------------------------------------------------------


def aggregate_failure_guidance_with_patterns(
    session: Session,
    *,
    charter_id: int,
    pattern_svc: PatternRetrievalService | None = None,
    charter_problem: str = "",
    current_context: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Extend aggregate_failure_guidance with cross-charter canonical patterns.

    Returns the same dict structure with an additional ``canonical_patterns`` key.
    """
    base = aggregate_failure_guidance(session, charter_id=charter_id)
    if pattern_svc is None or not charter_problem:
        base["canonical_patterns"] = []
        return base

    negative_hits = pattern_svc.search(
        session,
        query_text=charter_problem,
        polarity="negative",
        min_confidence=0.5,
        limit=10,
        current_context=current_context,
    )
    base["canonical_patterns"] = [
        {
            "public_id": hit.pattern.public_id,
            "title": hit.pattern.title,
            "description": hit.pattern.description,
            "pattern_type": hit.pattern.pattern_type,
            "category": hit.pattern.category,
            "confidence_score": hit.pattern.confidence_score,
            "proven_actions": hit.pattern.proven_actions,
            "disproven_actions": hit.pattern.disproven_actions,
        }
        for hit in negative_hits
    ]
    return base
