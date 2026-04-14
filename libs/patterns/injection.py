"""Pattern injection helper -- single entry point for operators that reuse patterns.

Usage from any operator:

    matches = inject_patterns(
        session,
        charter_id=ctx.charter_id,
        current_cycle_id=ctx.cycle_id,
        types=["failure", "remediation"],
        policy=policy,
        problem_profile_embedding=embedding_or_None,
    )

The helper applies auto-apply policy (see Phase 6 §2.1):
  * ``auto`` patterns pass if effective_confidence >= policy.min_confidence_auto.
  * ``curated`` patterns pass only if a valid PatternApproval exists for the
    charter (global approvals also count).
  * ``deprecated`` are excluded at retrieval time and never seen here.

Every successful injection emits a ``pattern.applied`` DomainEvent, so the
audit trail shows what biased a given operator run.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from libs.core.event_types import PatternEvents
from libs.core.events import emit_event_sync
from libs.patterns.retrieval import (
    PatternMatch,
    find_relevant_patterns,
    has_valid_approval,
)


@dataclass
class InjectionPolicy:
    """Runtime policy for pattern injection. Typically derived from ResearchCycle.config."""

    min_confidence_auto: float = 0.7
    max_staleness_days: int = 90
    cross_charter_weight_boost: float = 1.15
    cross_charter_only: bool = False
    limit: int = 10

    @classmethod
    def from_cycle_config(cls, config: dict | None) -> InjectionPolicy:
        cfg = (config or {}).get("patterns", {})
        return cls(
            min_confidence_auto=float(cfg.get("min_confidence_auto", 0.7)),
            max_staleness_days=int(cfg.get("max_staleness_days", 90)),
            cross_charter_weight_boost=float(
                cfg.get("cross_charter_weight_boost", 1.15)
            ),
            cross_charter_only=bool(cfg.get("cross_charter_only", False)),
            limit=int(cfg.get("injection_limit", 10)),
        )


def inject_patterns(
    session: Session,
    *,
    charter_id: UUID,
    current_cycle_id: UUID | None,
    types: list[str],
    policy: InjectionPolicy,
    problem_profile_embedding: list[float] | None = None,
    operator_name: str | None = None,
    emit_audit: bool = True,
) -> list[PatternMatch]:
    """Retrieve + policy-filter patterns for injection.

    Returns the filtered list of matches ready to be consumed by the caller.
    The caller decides how to render them (prompt context, scoring feature, etc.).
    """
    candidates = find_relevant_patterns(
        session,
        charter_id=charter_id,
        current_cycle_id=current_cycle_id,
        problem_profile_embedding=problem_profile_embedding,
        pattern_types=types,
        min_confidence=0.0,  # filter in policy layer, not SQL, so curated/auto both seen
        max_staleness_days=policy.max_staleness_days,
        cross_charter_only=policy.cross_charter_only,
        cross_charter_weight_boost=policy.cross_charter_weight_boost,
        limit=policy.limit * 3,
    )

    applied: list[PatternMatch] = []
    for m in candidates:
        tier = m.pattern.trust_tier
        if tier == "auto":
            if m.effective_confidence < policy.min_confidence_auto:
                continue
        elif tier == "curated":
            if not has_valid_approval(
                session, pattern_id=m.pattern.id, charter_id=charter_id
            ):
                continue
        else:
            # deprecated shouldn't appear (retrieval filters), but be safe.
            continue
        applied.append(m)
        if len(applied) >= policy.limit:
            break

    if emit_audit and applied:
        for m in applied:
            emit_event_sync(
                session,
                event_type=PatternEvents.applied.value,
                charter_id=charter_id,
                cycle_id=current_cycle_id,
                payload={
                    "pattern_id": str(m.pattern.id),
                    "pattern_type": m.pattern.pattern_type,
                    "trust_tier": m.pattern.trust_tier,
                    "effective_confidence": m.effective_confidence,
                    "operator": operator_name,
                },
            )
    return applied
