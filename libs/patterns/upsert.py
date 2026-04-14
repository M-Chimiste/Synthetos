"""Sync-session upsert helpers for canonical patterns and observations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.patterns.consolidation import AggregatedPattern, compute_confidence
from libs.storage.models.patterns import CanonicalPattern, PatternObservation


def upsert_pattern(
    session: Session,
    agg: AggregatedPattern,
    *,
    consolidation_version: int = 1,
) -> tuple[CanonicalPattern, bool]:
    """Upsert a canonical pattern keyed on (pattern_type, content_key).

    Returns (pattern, created) -- ``created`` is True if a new row was inserted.
    Existing rows are reinforced: evidence_count, source_charter_ids,
    confidence, last_observed_at, and last_reinforced_at are updated.
    """
    existing = session.execute(
        select(CanonicalPattern).where(
            CanonicalPattern.pattern_type == agg.pattern_type,
            CanonicalPattern.content_key == agg.content_key,
        )
    ).scalar_one_or_none()

    confidence = compute_confidence(agg)
    now = utcnow()

    if existing is None:
        pattern = CanonicalPattern(
            id=uuid7(),
            pattern_type=agg.pattern_type,
            content_key=agg.content_key,
            title=agg.title,
            summary=agg.summary,
            structured_body=agg.structured_body,
            evidence_count=agg.evidence_count,
            confidence=confidence,
            trust_tier="auto",
            first_observed_at=agg.first_observed_at,
            last_observed_at=agg.last_observed_at,
            last_reinforced_at=now,
            staleness_score=0.0,
            source_charter_ids=list(agg.charter_ids),
            consolidation_version=consolidation_version,
        )
        session.add(pattern)
        session.flush()
        return pattern, True

    # Reinforce existing pattern.
    existing_ids = set(existing.source_charter_ids or [])
    for cid in agg.charter_ids:
        existing_ids.add(cid)
    existing.source_charter_ids = list(existing_ids)

    existing.evidence_count = max(existing.evidence_count, agg.evidence_count)
    # If new aggregated covers more charters/evidence, re-derive confidence;
    # never lower an existing confidence on reinforcement.
    new_conf = compute_confidence(agg)
    if new_conf > existing.confidence:
        existing.confidence = new_conf
    existing.last_observed_at = max(existing.last_observed_at, agg.last_observed_at)
    existing.last_reinforced_at = now
    existing.staleness_score = 0.0
    existing.consolidation_version = consolidation_version
    # Refresh title/summary so edits to extractors propagate.
    existing.title = agg.title
    existing.summary = agg.summary
    merged_body: dict[str, Any] = dict(existing.structured_body or {})
    merged_body.update(agg.structured_body)
    existing.structured_body = merged_body
    # If tier was previously deprecated and evidence grew, lift back to curated
    # (not auto -- curation is explicit).
    if existing.trust_tier == "deprecated" and agg.cross_charter:
        existing.trust_tier = "curated"
    session.flush()
    return existing, False


def upsert_observations(
    session: Session,
    pattern: CanonicalPattern,
    agg: AggregatedPattern,
) -> int:
    """Insert observation rows for each candidate, skipping artifacts already linked."""
    if not agg.candidates:
        return 0

    existing_keys: set[tuple[str, UUID]] = set()
    rows = session.execute(
        select(
            PatternObservation.source_artifact_type,
            PatternObservation.source_artifact_id,
        ).where(PatternObservation.pattern_id == pattern.id)
    ).all()
    for row in rows:
        existing_keys.add((row[0], row[1]))

    inserted = 0
    for c in agg.candidates:
        key = (c.source_artifact_type, c.source_artifact_id)
        if key in existing_keys:
            continue
        obs = PatternObservation(
            id=uuid7(),
            pattern_id=pattern.id,
            charter_id=c.charter_id,
            cycle_id=c.cycle_id,
            source_artifact_type=c.source_artifact_type,
            source_artifact_id=c.source_artifact_id,
            contribution=c.contribution,
            observed_at=c.observed_at,
        )
        session.add(obs)
        inserted += 1
    if inserted:
        session.flush()
    return inserted
