"""Pattern staleness decay.

Pure logic: given a pattern and the current time, compute the new staleness
score and whether the trust tier should transition. Applied in bulk by the
``decay_patterns`` operator.

Rules:
  * ``staleness_score`` = (days_since_last_reinforced / max_staleness_days),
    clamped to [0, 1].
  * ``trust_tier`` transitions once per decay run, along the chain:
      auto    -> curated  once score >= 1.0
      curated -> deprecated once score >= 2.0 (i.e. 2x stale window)
  * Forcing (``force=True``) re-derives the tier every run regardless of
    staleness_score; used by the CLI/API for manual re-evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from libs.storage.models.patterns import CanonicalPattern


@dataclass
class DecayOutcome:
    """Result of evaluating one pattern for decay."""

    pattern_id: str
    previous_tier: str
    new_tier: str
    previous_staleness: float
    new_staleness: float
    demoted: bool
    deprecated: bool


def evaluate(
    pattern: CanonicalPattern,
    *,
    now: datetime,
    max_staleness_days: int,
    force: bool = False,
) -> DecayOutcome:
    """Evaluate one pattern and return the decay outcome (does not mutate)."""
    last = pattern.last_reinforced_at or pattern.last_observed_at
    age_days = (
        0.0 if last is None else max(0.0, (now - last).total_seconds() / 86400.0)
    )
    score = (
        0.0 if max_staleness_days <= 0 else age_days / float(max_staleness_days)
    )

    previous_tier = pattern.trust_tier
    new_tier = previous_tier
    if previous_tier == "auto" and score >= 1.0:
        new_tier = "curated"
    if previous_tier == "curated" and score >= 2.0:
        new_tier = "deprecated"
    if force and pattern.evidence_count <= 0:
        new_tier = "deprecated"

    return DecayOutcome(
        pattern_id=str(pattern.id),
        previous_tier=previous_tier,
        new_tier=new_tier,
        previous_staleness=pattern.staleness_score,
        new_staleness=round(min(score, 2.0), 4),
        demoted=(previous_tier == "auto" and new_tier == "curated"),
        deprecated=(new_tier == "deprecated" and previous_tier != "deprecated"),
    )
