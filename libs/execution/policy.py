from __future__ import annotations

from dataclasses import dataclass

from libs.core.config import AppConfig


@dataclass(frozen=True)
class ExecutionPolicyDecision:
    allowed: bool
    requires_force_start: bool
    reason: str | None = None


def evaluate_run_policy(
    config: AppConfig,
    *,
    execution_profile: str,
    network_mode: str,
    image_key: str,
    force_start: bool,
) -> ExecutionPolicyDecision:
    policy = config.load_yaml(config.policy_config_path).get("execution", {})
    auto_profiles = set(policy.get("auto_run_profiles", []))
    deny_rules = policy.get("deny_without_force_start", {})

    if network_mode in set(deny_rules.get("network_mode", [])) and not force_start:
        return ExecutionPolicyDecision(
            allowed=False,
            requires_force_start=True,
            reason="Network-enabled runs require force_start approval.",
        )
    if image_key in set(deny_rules.get("image_keys", [])) and not force_start:
        return ExecutionPolicyDecision(
            allowed=False,
            requires_force_start=True,
            reason="This image/build recipe is not auto-approved.",
        )
    if execution_profile not in auto_profiles and not force_start:
        return ExecutionPolicyDecision(
            allowed=False,
            requires_force_start=True,
            reason=f"Execution profile {execution_profile!r} is not auto-approved.",
        )
    return ExecutionPolicyDecision(allowed=True, requires_force_start=False, reason=None)
