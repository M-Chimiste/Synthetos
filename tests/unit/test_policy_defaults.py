"""Tests for policy configuration parsing, defaults, and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from libs.core.config import AppConfig, PolicyConfig


class TestPolicyConfig:
    def test_defaults(self) -> None:
        policy = PolicyConfig()
        assert policy.max_retry_attempts == 3
        assert policy.max_concurrent_runs == 2
        assert policy.lease_timeout_minutes == 5
        assert policy.skill_validation_mode == "strict"

    def test_from_raw_full(self) -> None:
        raw = {
            "execution": {
                "max_retry_attempts": 5,
                "max_concurrent_runs": 4,
                "lease_timeout_minutes": 10,
            },
            "skills": {
                "validation_mode": "lenient",
            },
        }
        policy = PolicyConfig.from_raw(raw)
        assert policy.max_retry_attempts == 5
        assert policy.max_concurrent_runs == 4
        assert policy.lease_timeout_minutes == 10
        assert policy.skill_validation_mode == "lenient"

    def test_from_raw_missing_keys_use_defaults(self) -> None:
        policy = PolicyConfig.from_raw({})
        assert policy.max_retry_attempts == 3
        assert policy.max_concurrent_runs == 2
        assert policy.lease_timeout_minutes == 5
        assert policy.skill_validation_mode == "strict"

    def test_validate_policy_valid(self) -> None:
        policy = PolicyConfig()
        assert policy.validate_policy() == []

    def test_validate_policy_negative_retries(self) -> None:
        policy = PolicyConfig(max_retry_attempts=-1)
        errors = policy.validate_policy()
        assert any("max_retry_attempts" in e for e in errors)

    def test_validate_policy_zero_concurrent(self) -> None:
        policy = PolicyConfig(max_concurrent_runs=0)
        errors = policy.validate_policy()
        assert any("max_concurrent_runs" in e for e in errors)

    def test_validate_policy_zero_lease(self) -> None:
        policy = PolicyConfig(lease_timeout_minutes=0)
        errors = policy.validate_policy()
        assert any("lease_timeout_minutes" in e for e in errors)

    def test_validate_policy_bad_validation_mode(self) -> None:
        policy = PolicyConfig(skill_validation_mode="chaos")
        errors = policy.validate_policy()
        assert any("validation_mode" in e for e in errors)


class TestAppConfigPolicy:
    def test_policy_from_real_config_file(self) -> None:
        config_path = Path("configs/policies/default.yaml")
        if not config_path.exists():
            pytest.skip("Policy config file not found")
        config = AppConfig(policy_config_path=config_path)
        policy = config.policy
        assert policy.max_retry_attempts == 3
        assert policy.max_concurrent_runs == 2
        assert policy.lease_timeout_minutes == 5
        assert policy.skill_validation_mode == "strict"

    def test_policy_from_missing_file_uses_defaults(self, tmp_path: Path) -> None:
        config = AppConfig(policy_config_path=tmp_path / "nonexistent.yaml")
        policy = config.policy
        assert policy.max_retry_attempts == 3
        assert policy.skill_validation_mode == "strict"

    def test_policy_validates_clean(self) -> None:
        config_path = Path("configs/policies/default.yaml")
        if not config_path.exists():
            pytest.skip("Policy config file not found")
        config = AppConfig(policy_config_path=config_path)
        errors = config.policy.validate_policy()
        assert errors == []
