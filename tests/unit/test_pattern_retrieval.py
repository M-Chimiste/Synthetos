"""Tests for pattern retrieval service."""

from __future__ import annotations

from unittest.mock import MagicMock

from libs.memory.retrieval import PatternRetrievalService


class TestPatternRetrievalService:
    def test_get_failure_patterns_filters_by_class(self) -> None:
        """Direct lookup should filter patterns by failure_class in trigger_conditions."""
        session = MagicMock()
        pat1 = MagicMock()
        pat1.trigger_conditions = ["oom_or_resource_limit", "large_model"]
        pat2 = MagicMock()
        pat2.trigger_conditions = ["dependency_failure"]
        session.scalars.return_value.all.return_value = [pat1, pat2]

        embedder = MagicMock()
        svc = PatternRetrievalService(embedder)
        results = svc.get_failure_patterns(
            session, failure_class="oom_or_resource_limit",
        )
        assert pat1 in results
        assert pat2 not in results

    def test_get_failure_patterns_no_class_filter(self) -> None:
        """Without failure_class, all active patterns should be returned."""
        session = MagicMock()
        pat1 = MagicMock()
        pat1.trigger_conditions = ["oom"]
        session.scalars.return_value.all.return_value = [pat1]

        embedder = MagicMock()
        svc = PatternRetrievalService(embedder)
        results = svc.get_failure_patterns(session)
        assert len(results) == 1

    def test_merge_and_rank(self) -> None:
        """Hybrid scoring should combine lexical and vector scores."""
        session = MagicMock()
        pattern = MagicMock()
        pattern.id = 1
        session.scalars.return_value.all.return_value = [pattern]

        lexical_rows = [{"id": 1, "lexical_score": 0.8}]
        vector_rows = [{"id": 1, "vector_score": 0.6}]

        hits = PatternRetrievalService._merge_and_rank(
            session, lexical_rows, vector_rows, limit=10,
        )
        assert len(hits) == 1
        # 0.5 * (0.8/0.8) + 0.5 * 0.6 = 0.5 + 0.3 = 0.8
        assert hits[0].hybrid_score == 0.8

    def test_merge_and_rank_empty(self) -> None:
        session = MagicMock()
        hits = PatternRetrievalService._merge_and_rank(session, [], [], 10)
        assert hits == []

    def test_list_categories(self) -> None:
        session = MagicMock()
        session.scalars.return_value.all.return_value = [
            "failure/oom", "method/optimization", "signal/plateau",
        ]
        embedder = MagicMock()
        svc = PatternRetrievalService(embedder)
        cats = svc.list_categories(session)
        assert len(cats) == 3

    def test_get_failure_patterns_respects_staleness_context(self) -> None:
        session = MagicMock()
        matching = MagicMock()
        matching.trigger_conditions = ["oom"]
        matching.staleness_context = {"hardware": "A100"}
        mismatched = MagicMock()
        mismatched.trigger_conditions = ["oom"]
        mismatched.staleness_context = {"hardware": "H100"}
        session.scalars.return_value.all.return_value = [matching, mismatched]

        svc = PatternRetrievalService(MagicMock())
        results = svc.get_failure_patterns(
            session,
            failure_class="oom",
            current_context={"hardware": "A100"},
        )
        assert results == [matching]

    def test_build_category_tree(self) -> None:
        tree = PatternRetrievalService.build_category_tree([
            "failure/resource/oom",
            "failure/resource/cpu",
            "signal/frontier/breakthrough",
        ])
        assert len(tree) == 2
        assert tree[0]["name"] == "failure"
        assert tree[0]["children"][0]["path"].startswith("failure/")
