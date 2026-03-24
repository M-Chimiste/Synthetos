"""Tests for cross-charter pattern consolidation logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest

from libs.core.policy import MemoryPolicyConfig
from libs.memory.consolidation import (
    _cosine_similarity_matrix,
    _UnionFind,
    apply_staleness_decay,
    check_staleness_context,
    cluster_postmortems_by_failure,
    upsert_canonical_pattern,
)

# ---------------------------------------------------------------------------
# UnionFind
# ---------------------------------------------------------------------------


class TestUnionFind:
    def test_basic_merge(self) -> None:
        uf = _UnionFind(5)
        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(1, 3)
        groups = uf.groups()
        merged = None
        for members in groups.values():
            if 0 in members:
                merged = set(members)
        assert merged == {0, 1, 2, 3}

    def test_no_merge(self) -> None:
        uf = _UnionFind(3)
        groups = uf.groups()
        assert len(groups) == 3


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        vecs = np.array([[1.0, 0.0], [1.0, 0.0]])
        sim = _cosine_similarity_matrix(vecs)
        assert sim[0, 1] == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        vecs = np.array([[1.0, 0.0], [0.0, 1.0]])
        sim = _cosine_similarity_matrix(vecs)
        assert sim[0, 1] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _make_postmortem(
    failure_class: str = "oom_or_resource_limit",
    root_cause_summary: str = "OOM on large batch",
    contributing_factors: list[str] | None = None,
    charter_id: int = 1,
) -> MagicMock:
    pm = MagicMock()
    pm.failure_class = failure_class
    pm.root_cause_summary = root_cause_summary
    pm.contributing_factors = contributing_factors or []
    pm.cycle = MagicMock()
    pm.cycle.charter_id = charter_id
    pm.public_id = f"pm-test-{id(pm)}"
    pm.failure_stage = "execution"
    pm.remediation_suggestions = []
    pm.created_at = datetime.now(UTC)
    return pm


class TestClusterPostmortemsByFailure:
    def test_clusters_formed_above_threshold(self) -> None:
        """Three similar postmortems across 2 charters should form a cluster."""
        embedder = MagicMock()
        # Return similar vectors for all 3
        embedder.embed_documents.return_value = [
            [1.0, 0.0, 0.0],
            [0.99, 0.1, 0.0],
            [0.98, 0.05, 0.0],
        ]
        postmortems = [
            _make_postmortem(charter_id=1),
            _make_postmortem(charter_id=2),
            _make_postmortem(charter_id=1),
        ]
        policy = MemoryPolicyConfig(
            min_cluster_size=3,
            min_charters_for_pattern=2,
            similarity_threshold=0.9,
        )
        clusters = cluster_postmortems_by_failure(postmortems, embedder, policy)
        assert len(clusters) == 1
        assert len(clusters[0].members) == 3

    def test_no_cluster_below_min_size(self) -> None:
        """Two postmortems should not form a cluster with min_cluster_size=3."""
        embedder = MagicMock()
        embedder.embed_documents.return_value = [[1.0, 0.0], [0.99, 0.1]]
        postmortems = [
            _make_postmortem(charter_id=1),
            _make_postmortem(charter_id=2),
        ]
        policy = MemoryPolicyConfig(min_cluster_size=3, min_charters_for_pattern=2)
        clusters = cluster_postmortems_by_failure(postmortems, embedder, policy)
        assert len(clusters) == 0

    def test_no_cluster_single_charter(self) -> None:
        """Postmortems from only one charter should not form a cross-charter cluster."""
        embedder = MagicMock()
        embedder.embed_documents.return_value = [
            [1.0, 0.0], [0.99, 0.1], [0.98, 0.05],
        ]
        postmortems = [
            _make_postmortem(charter_id=1),
            _make_postmortem(charter_id=1),
            _make_postmortem(charter_id=1),
        ]
        policy = MemoryPolicyConfig(
            min_cluster_size=3, min_charters_for_pattern=2, similarity_threshold=0.9,
        )
        clusters = cluster_postmortems_by_failure(postmortems, embedder, policy)
        assert len(clusters) == 0


# ---------------------------------------------------------------------------
# Staleness & context
# ---------------------------------------------------------------------------


class TestStalenessDecay:
    def test_decay_applied(self) -> None:
        session = MagicMock()
        pattern = MagicMock()
        pattern.status = "active"
        pattern.confidence_score = 1.0
        pattern.last_validated_at = datetime.now(UTC) - timedelta(days=60)
        session.scalars.return_value.all.return_value = [pattern]

        policy = MemoryPolicyConfig(
            decay_factor=0.9, decay_interval_days=30, revalidation_threshold=0.3,
        )
        count = apply_staleness_decay(session, policy)
        assert count == 1
        assert pattern.confidence_score == pytest.approx(0.9)

    def test_below_threshold_marks_revalidation(self) -> None:
        session = MagicMock()
        pattern = MagicMock()
        pattern.status = "active"
        pattern.confidence_score = 0.25
        pattern.last_validated_at = datetime.now(UTC) - timedelta(days=60)
        session.scalars.return_value.all.return_value = [pattern]

        policy = MemoryPolicyConfig(
            decay_factor=0.9, decay_interval_days=30, revalidation_threshold=0.3,
        )
        apply_staleness_decay(session, policy)
        assert pattern.status == "needs_revalidation"


class TestCheckStalenessContext:
    def test_matching_context(self) -> None:
        pattern = MagicMock()
        pattern.staleness_context = {"torch_version": "2.x", "hardware": "A100"}
        assert check_staleness_context(pattern, {"torch_version": "2.x", "hardware": "A100"})

    def test_mismatched_context(self) -> None:
        pattern = MagicMock()
        pattern.staleness_context = {"torch_version": "2.x"}
        assert not check_staleness_context(pattern, {"torch_version": "3.0"})

    def test_empty_context_always_applicable(self) -> None:
        pattern = MagicMock()
        pattern.staleness_context = {}
        assert check_staleness_context(pattern, {"torch_version": "3.0"})


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


class TestUpsertCanonicalPattern:
    def test_creates_new_pattern(self) -> None:
        session = MagicMock()
        session.scalars.return_value.first.return_value = None  # No existing

        embedder = MagicMock()
        embedder.embed_query.return_value = [0.1] * 768

        extracted = {
            "title": "OOM on large batch sizes",
            "pattern_type": "failure_pattern",
            "polarity": "negative",
            "description": "A common OOM pattern",
            "category": "resource/oom",
            "trigger_conditions": ["batch_size > 32"],
            "proven_actions": [
                {"action": "reduce batch", "success_rate": 0.9, "evidence_count": 3},
            ],
            "disproven_actions": ["increase memory"],
            "staleness_context": {"hardware": "A100"},
        }
        refs = [{"charter_public_id": "charter-1", "ref_type": "postmortem", "public_id": "pm-1"}]

        pattern = upsert_canonical_pattern(session, extracted, refs, embedder)
        session.add.assert_called_once()
        assert pattern.title == "OOM on large batch sizes"
        assert pattern.category == "resource/oom"
        assert pattern.evidence_count == 1

    def test_merges_existing_pattern(self) -> None:
        existing = MagicMock()
        existing.evidence_refs = [
            {"public_id": "pm-1", "charter_public_id": "charter-1"},
        ]
        existing.title = "OOM on large batch sizes"

        session = MagicMock()
        session.scalars.return_value.first.return_value = existing

        embedder = MagicMock()
        embedder.embed_query.return_value = [0.1] * 768

        extracted = {
            "title": "OOM on large batch sizes",
            "pattern_type": "failure_pattern",
            "description": "Updated description",
            "category": "resource/oom",
        }
        new_refs = [
            {"public_id": "pm-2", "charter_public_id": "charter-2"},
        ]

        result = upsert_canonical_pattern(session, extracted, new_refs, embedder)
        assert result is existing
        assert len(existing.evidence_refs) == 2
        assert existing.evidence_count == 2
