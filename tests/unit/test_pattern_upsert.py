"""Pattern upsert regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from uuid_utils import uuid7

from libs.patterns.consolidation import AggregatedPattern
from libs.patterns.upsert import upsert_pattern


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FakeSession:
    def __init__(self, existing: object) -> None:
        self.existing = existing
        self.flushed = False

    def execute(self, _stmt: object) -> _ScalarResult:
        return _ScalarResult(self.existing)

    def flush(self) -> None:
        self.flushed = True


def test_upsert_pattern_reinforces_naive_existing_timestamp_with_aware_aggregate() -> None:
    naive_observed = datetime(2026, 6, 8, 12, 0, 0)
    aware_observed = datetime(2026, 6, 8, 12, 30, 0, tzinfo=UTC)
    existing = SimpleNamespace(
        pattern_type="failure",
        content_key="metric-parse",
        title="old",
        summary="old",
        structured_body={},
        evidence_count=1,
        confidence=0.1,
        trust_tier="auto",
        source_charter_ids=[],
        last_observed_at=naive_observed,
        last_reinforced_at=naive_observed,
        staleness_score=1.0,
        consolidation_version=1,
    )
    charter_id = uuid7()
    agg = AggregatedPattern(
        pattern_type="failure",
        content_key="metric-parse",
        title="new",
        summary="new",
        structured_body={"root_cause": "metrics contract mismatch"},
        evidence_count=2,
        charter_ids=[charter_id],
        first_observed_at=aware_observed - timedelta(minutes=5),
        last_observed_at=aware_observed,
    )
    session = _FakeSession(existing)

    pattern, created = upsert_pattern(session, agg)

    assert created is False
    assert pattern is existing
    assert pattern.last_observed_at == aware_observed
    assert pattern.source_charter_ids == [charter_id]
    assert pattern.title == "new"
    assert session.flushed is True
