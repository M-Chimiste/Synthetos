"""Tests for memory policy configuration."""

from __future__ import annotations

from libs.core.policy import MemoryPolicyConfig, load_memory_policy


class TestMemoryPolicyConfig:
    def test_defaults(self) -> None:
        policy = MemoryPolicyConfig()
        assert policy.enabled is True
        assert policy.consolidation_interval_hours == 24
        assert policy.min_cluster_size == 3
        assert policy.min_charters_for_pattern == 2
        assert policy.similarity_threshold == 0.75
        assert policy.decay_factor == 0.9
        assert policy.decay_interval_days == 30
        assert policy.revalidation_threshold == 0.3
        assert policy.min_confidence_for_injection == 0.5
        assert policy.max_patterns_per_query == 5


class TestLoadMemoryPolicy:
    def test_load_from_dict(self) -> None:
        raw = {
            "memory": {
                "enabled": False,
                "min_cluster_size": 5,
                "decay_factor": 0.8,
            }
        }
        policy = load_memory_policy(raw)
        assert policy.enabled is False
        assert policy.min_cluster_size == 5
        assert policy.decay_factor == 0.8
        # Defaults preserved for unspecified fields
        assert policy.consolidation_interval_hours == 24

    def test_load_empty_section(self) -> None:
        policy = load_memory_policy({})
        assert policy.enabled is True
        assert policy.min_cluster_size == 3

    def test_load_legacy_interval_key(self) -> None:
        policy = load_memory_policy({"memory": {"consolidation_interval_cycles": 12}})
        assert policy.consolidation_interval_hours == 12
