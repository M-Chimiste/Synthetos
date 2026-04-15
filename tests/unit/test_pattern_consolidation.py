"""Tests for canonical pattern aggregation + confidence scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from uuid_utils import uuid7

from libs.patterns import content_key
from libs.patterns.consolidation import (
    PatternCandidate,
    aggregate,
    compute_confidence,
    extract_failure,
    extract_remediation,
)


def _utc(offset_minutes: int = 0) -> datetime:
    return datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC) + timedelta(
        minutes=offset_minutes
    )


def _candidate(
    pattern_type: str = "failure",
    key: str = "k1",
    charter_id=None,
    cycle_id=None,
    observed_at=None,
) -> PatternCandidate:
    return PatternCandidate(
        pattern_type=pattern_type,
        content_key=key,
        title="t",
        summary="s",
        structured_body={"k": "v"},
        charter_id=charter_id or uuid7(),
        cycle_id=cycle_id or uuid7(),
        source_artifact_type="postmortem",
        source_artifact_id=uuid7(),
        observed_at=observed_at or _utc(),
    )


class TestAggregate:
    def test_groups_by_type_and_key(self) -> None:
        c1 = _candidate(key="a")
        c2 = _candidate(key="a")
        c3 = _candidate(key="b")
        out = aggregate([c1, c2, c3])
        assert len(out) == 2
        by_key = {a.content_key: a for a in out}
        assert by_key["a"].evidence_count == 2
        assert by_key["b"].evidence_count == 1

    def test_charter_set_is_unique(self) -> None:
        cid = uuid7()
        cycle = uuid7()
        c1 = _candidate(key="a", charter_id=cid, cycle_id=cycle)
        c2 = _candidate(key="a", charter_id=cid, cycle_id=cycle)
        out = aggregate([c1, c2])
        assert len(out) == 1
        assert len(out[0].charter_ids) == 1

    def test_cross_charter_flag(self) -> None:
        c1 = _candidate(key="a", charter_id=uuid7())
        c2 = _candidate(key="a", charter_id=uuid7())
        out = aggregate([c1, c2])
        assert out[0].cross_charter is True

    def test_first_and_last_observed_use_extremes(self) -> None:
        c_old = _candidate(key="a", observed_at=_utc(-60))
        c_new = _candidate(key="a", observed_at=_utc(60))
        out = aggregate([c_new, c_old])
        assert out[0].first_observed_at == _utc(-60)
        assert out[0].last_observed_at == _utc(60)


class TestConfidence:
    def _agg_with(self, evidence_count: int, charters: int):
        candidates = [
            _candidate(key="a", charter_id=uuid7() if charters > 1 else None)
            for _ in range(evidence_count)
        ]
        # Force charter count
        out = aggregate(candidates)
        out[0].charter_ids = [uuid7() for _ in range(charters)]
        out[0].evidence_count = evidence_count
        return out[0]

    def test_single_observation_baseline(self) -> None:
        agg = self._agg_with(1, 1)
        assert compute_confidence(agg) == 0.35

    def test_two_observations_higher(self) -> None:
        agg = self._agg_with(2, 1)
        assert compute_confidence(agg) > 0.35

    def test_cross_charter_boost(self) -> None:
        single = self._agg_with(2, 1)
        cross = self._agg_with(2, 2)
        assert compute_confidence(cross) > compute_confidence(single)

    def test_capped_at_high_evidence(self) -> None:
        agg = self._agg_with(20, 1)
        # base capped at 0.80 for single-charter
        assert compute_confidence(agg) <= 0.80


class TestExtractors:
    def test_failure_uses_failure_key(self) -> None:
        pm = MagicMock()
        pm.id = uuid7()
        pm.charter_id = uuid7()
        pm.cycle_id = uuid7()
        pm.failure_class = "oom"
        pm.root_cause = "GPU memory exhausted"
        pm.contributing_factors = []
        pm.lessons = []
        pm.next_step_recommendation = "reduce batch"
        pm.created_at = _utc()
        candidate = extract_failure(pm)
        expected = content_key.failure_key(
            failure_class="oom", root_cause="gpu memory exhausted"
        )
        assert candidate.content_key == expected
        assert candidate.source_artifact_type == "postmortem"

    def test_remediation_uses_remediation_key(self) -> None:
        ra = MagicMock()
        ra.id = uuid7()
        ra.charter_id = uuid7()
        ra.cycle_id = uuid7()
        ra.failure_class = "oom"
        ra.strategy = "reduce_batch"
        ra.strategy_tier = "focused"
        ra.outcome = "retry_created"
        ra.attempt_number = 1
        ra.action_detail = None
        ra.reasoning = "shrink"
        ra.created_at = _utc()
        candidate = extract_remediation(ra)
        expected = content_key.remediation_key(
            failure_class="oom", strategy="reduce_batch", outcome="retry_created"
        )
        assert candidate.content_key == expected
