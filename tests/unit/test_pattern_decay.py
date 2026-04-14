"""Tests for pattern staleness decay logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from libs.patterns.decay import evaluate


def _pattern(*, tier="auto", last_reinforced=None, evidence_count=3):
    p = MagicMock()
    p.id = "p1"
    p.trust_tier = tier
    p.last_reinforced_at = last_reinforced
    p.last_observed_at = last_reinforced
    p.staleness_score = 0.0
    p.evidence_count = evidence_count
    return p


def test_fresh_pattern_no_change() -> None:
    now = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
    p = _pattern(last_reinforced=now)
    out = evaluate(p, now=now, max_staleness_days=90)
    assert out.new_tier == "auto"
    assert out.demoted is False
    assert out.deprecated is False
    assert out.new_staleness == 0.0


def test_auto_demotes_after_threshold() -> None:
    now = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
    last = now - timedelta(days=100)  # >90
    p = _pattern(last_reinforced=last)
    out = evaluate(p, now=now, max_staleness_days=90)
    assert out.new_tier == "curated"
    assert out.demoted is True


def test_curated_deprecates_at_2x() -> None:
    now = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
    last = now - timedelta(days=200)
    p = _pattern(tier="curated", last_reinforced=last)
    out = evaluate(p, now=now, max_staleness_days=90)
    assert out.new_tier == "deprecated"
    assert out.deprecated is True


def test_force_deprecates_zero_evidence() -> None:
    now = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
    p = _pattern(last_reinforced=now, evidence_count=0)
    out = evaluate(p, now=now, max_staleness_days=90, force=True)
    assert out.new_tier == "deprecated"


def test_no_reinforcement_record_treats_as_fresh() -> None:
    now = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
    p = _pattern(last_reinforced=None)
    out = evaluate(p, now=now, max_staleness_days=90)
    assert out.new_tier == "auto"
