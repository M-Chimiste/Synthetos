"""Canonical pattern retrieval.

``find_relevant_patterns`` is the single entry point used by the injection
helper and the ``retrieve-preview`` API endpoint. It:
  * filters out ``deprecated`` patterns,
  * excludes patterns observed *only* in the current cycle,
  * ranks by cosine similarity (when an embedding is provided) and
    decays effective confidence by staleness,
  * returns ranked ``PatternMatch`` dataclasses with source_charter_ids
    surfaced for cross-charter weighting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from libs.core.clock import utcnow
from libs.storage.models.patterns import (
    CanonicalPattern,
    PatternApproval,
    PatternObservation,
)


@dataclass
class PatternMatch:
    """A pattern retrieved for reuse, with scores surfaced for injection policy."""

    pattern: CanonicalPattern
    similarity: float | None
    effective_confidence: float
    cross_charter: bool
    source_charter_ids: list[UUID]

    def to_context(self) -> dict[str, Any]:
        """Compact dict form suitable for injecting into prompts."""
        p = self.pattern
        return {
            "id": str(p.id),
            "pattern_type": p.pattern_type,
            "title": p.title,
            "summary": p.summary,
            "trust_tier": p.trust_tier,
            "evidence_count": p.evidence_count,
            "confidence": p.confidence,
            "effective_confidence": self.effective_confidence,
            "cross_charter": self.cross_charter,
            "structured_body": p.structured_body,
        }


def _effective_confidence(
    pattern: CanonicalPattern,
    *,
    max_staleness_days: int,
    now: datetime,
) -> float:
    """Linearly decay confidence toward 0 over ``max_staleness_days`` days.

    Past the threshold, effective confidence floors at a small residual so
    the retrieval SQL can still rank but the injection policy will reject.
    """
    if max_staleness_days <= 0:
        return pattern.confidence
    last = pattern.last_reinforced_at or pattern.last_observed_at
    if last is None:
        return pattern.confidence
    age_days = max(0.0, (now - last).total_seconds() / 86400.0)
    decay = min(age_days / float(max_staleness_days), 1.0)
    return max(0.0, pattern.confidence * (1.0 - decay))


def _cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if a is None or b is None:
        return None
    import math

    if len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return None
    return dot / (na * nb)


def find_relevant_patterns(
    session: Session,
    *,
    charter_id: UUID,
    current_cycle_id: UUID | None,
    problem_profile_embedding: list[float] | None = None,
    pattern_types: list[str] | None = None,
    min_confidence: float = 0.0,
    max_staleness_days: int = 90,
    cross_charter_only: bool = False,
    cross_charter_weight_boost: float = 1.15,
    limit: int = 20,
) -> list[PatternMatch]:
    """Retrieve patterns relevant to the given charter + problem profile.

    Notes:
      * ``current_cycle_id`` enables the "exclude patterns whose observations
        are entirely from the current cycle" rule. If None, no such exclusion.
      * Curated patterns without a valid approval are still returned here;
        the injection helper applies approval gating (it needs charter scope).
      * Deprecated patterns are excluded.
    """
    stmt = select(CanonicalPattern).where(
        CanonicalPattern.trust_tier != "deprecated"
    )
    if pattern_types:
        stmt = stmt.where(CanonicalPattern.pattern_type.in_(pattern_types))
    if min_confidence > 0:
        stmt = stmt.where(CanonicalPattern.confidence >= min_confidence)

    if current_cycle_id is not None:
        other_cycle_exists = (
            select(PatternObservation.id)
            .where(PatternObservation.pattern_id == CanonicalPattern.id)
            .where(PatternObservation.cycle_id != current_cycle_id)
        )
        stmt = stmt.where(exists(other_cycle_exists))

    if cross_charter_only:
        stmt = stmt.where(func.cardinality(CanonicalPattern.source_charter_ids) > 1)

    # Light over-fetch so Python-side ranking has a pool; hard cap at 200.
    stmt = stmt.limit(max(limit * 5, limit))

    rows = session.execute(stmt).scalars().all()
    now = utcnow()

    matches: list[PatternMatch] = []
    for p in rows:
        sim = _cosine(problem_profile_embedding, list(p.embedding) if p.embedding else None)
        eff = _effective_confidence(p, max_staleness_days=max_staleness_days, now=now)
        charters = list(p.source_charter_ids or [])
        cross_charter = len({c for c in charters}) > 1
        boosted = eff * (cross_charter_weight_boost if cross_charter else 1.0)
        matches.append(
            PatternMatch(
                pattern=p,
                similarity=sim,
                effective_confidence=round(boosted, 4),
                cross_charter=cross_charter,
                source_charter_ids=charters,
            )
        )

    def sort_key(m: PatternMatch) -> tuple[float, float]:
        sim = m.similarity if m.similarity is not None else 0.0
        return (sim, m.effective_confidence)

    matches.sort(key=sort_key, reverse=True)
    return matches[:limit]


def has_valid_approval(
    session: Session,
    *,
    pattern_id: UUID,
    charter_id: UUID,
) -> bool:
    """True if an approve decision exists (global or for the given charter) that
    has not expired or been superseded by a later reject for the same scope.
    """
    now = utcnow()
    rows = session.execute(
        select(PatternApproval)
        .where(PatternApproval.pattern_id == pattern_id)
        .where(
            (PatternApproval.charter_id == charter_id)
            | (PatternApproval.charter_id.is_(None))
        )
        .order_by(PatternApproval.created_at.desc())
    ).scalars().all()

    # Group by scope; latest row per scope wins.
    latest_by_scope: dict[UUID | None, PatternApproval] = {}
    for row in rows:
        scope = row.charter_id
        if scope not in latest_by_scope:
            latest_by_scope[scope] = row

    for approval in latest_by_scope.values():
        if approval.decision != "approve":
            continue
        if approval.expires_at is not None and approval.expires_at < now:
            continue
        return True
    return False
