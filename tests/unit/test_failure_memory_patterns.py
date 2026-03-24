"""Tests for pattern-aware failure memory extension."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from libs.verification.failure_memory import aggregate_failure_guidance_with_patterns


class TestAggregateWithPatterns:
    @patch("libs.verification.failure_memory.aggregate_failure_guidance")
    def test_without_pattern_service(self, mock_agg: MagicMock) -> None:
        """Without a pattern service, canonical_patterns should be empty."""
        mock_agg.return_value = {
            "retrieval_guidance": [],
            "protocol_guidance": [],
            "ranking_caution_signals": [],
        }
        session = MagicMock()
        result = aggregate_failure_guidance_with_patterns(
            session, charter_id=1, pattern_svc=None, charter_problem="test",
        )
        assert result["canonical_patterns"] == []
        assert "retrieval_guidance" in result

    @patch("libs.verification.failure_memory.aggregate_failure_guidance")
    def test_with_pattern_service(self, mock_agg: MagicMock) -> None:
        """With a pattern service, canonical_patterns should include negative matches."""
        mock_agg.return_value = {
            "retrieval_guidance": [],
            "protocol_guidance": [],
            "ranking_caution_signals": [],
        }
        session = MagicMock()
        pattern_svc = MagicMock()
        hit = MagicMock()
        hit.pattern.public_id = "pat-test"
        hit.pattern.title = "OOM pattern"
        hit.pattern.description = "A known OOM issue"
        hit.pattern.pattern_type = "failure_pattern"
        hit.pattern.category = "resource/oom"
        hit.pattern.confidence_score = 0.9
        hit.pattern.proven_actions = [{"action": "reduce batch", "success_rate": 0.8}]
        hit.pattern.disproven_actions = ["increase memory"]
        pattern_svc.search.return_value = [hit]

        result = aggregate_failure_guidance_with_patterns(
            session,
            charter_id=1,
            pattern_svc=pattern_svc,
            charter_problem="ML experiment optimization",
        )
        assert len(result["canonical_patterns"]) == 1
        assert result["canonical_patterns"][0]["title"] == "OOM pattern"
        assert result["canonical_patterns"][0]["category"] == "resource/oom"

    @patch("libs.verification.failure_memory.aggregate_failure_guidance")
    def test_empty_problem_skips_patterns(self, mock_agg: MagicMock) -> None:
        """Empty charter_problem should skip pattern retrieval."""
        mock_agg.return_value = {
            "retrieval_guidance": [],
            "protocol_guidance": [],
            "ranking_caution_signals": [],
        }
        session = MagicMock()
        pattern_svc = MagicMock()
        result = aggregate_failure_guidance_with_patterns(
            session, charter_id=1, pattern_svc=pattern_svc, charter_problem="",
        )
        assert result["canonical_patterns"] == []
        pattern_svc.search.assert_not_called()
