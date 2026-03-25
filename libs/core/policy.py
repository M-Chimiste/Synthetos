from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, model_validator


class TokenScope(StrEnum):
    CYCLES_READ = "cycles.read"
    CYCLES_WRITE = "cycles.write"
    RUNS_CONTROL = "runs.control"
    REPORTS_READ = "reports.read"
    SKILLS_READ = "skills.read"
    EVENTS_READ = "events.read"
    ADMIN_LOCAL = "admin.local"


@dataclass(frozen=True)
class Actor:
    actor_id: str
    client_id: str
    scopes: frozenset[TokenScope]


SYSTEM_ACTOR = Actor(
    actor_id="system:worker",
    client_id="system",
    scopes=frozenset(scope for scope in TokenScope),
)


class RemediationPolicyConfig(BaseModel):
    enabled: bool = True
    max_attempts_per_run: int = 3
    focused_failure_classes: list[str] = [
        "dependency_failure",
        "runtime_exception",
        "metric_parse_failure",
        "invalid_artifact_output",
    ]
    full_debug_failure_classes: list[str] = [
        "timeout",
        "oom_or_resource_limit",
    ]
    escalate_to_full_debug_after: int = 1
    max_stderr_chars: int = 3000
    max_code_chars: int = 8000


def load_remediation_policy(raw_policy: dict[str, Any]) -> RemediationPolicyConfig:
    """Parse the 'remediation' section from policy YAML."""
    section = raw_policy.get("remediation", {})
    return RemediationPolicyConfig.model_validate(section)


class AutonomyPolicyConfig(BaseModel):
    mode: str = "supervised"  # "supervised" | "autonomous"
    auto_pivot_on_stall: bool = True
    auto_pivot_on_regression: bool = True
    auto_continue_on_advancing: bool = True
    auto_regenerate_hypotheses: bool = True
    escalate_on_portfolio_exhausted: bool = True


def load_autonomy_policy(raw_policy: dict[str, Any]) -> AutonomyPolicyConfig:
    """Parse the 'autonomy' section from policy YAML."""
    section = raw_policy.get("autonomy", {})
    return AutonomyPolicyConfig.model_validate(section)


class MemoryPolicyConfig(BaseModel):
    enabled: bool = True
    consolidation_interval_hours: int = 24
    min_cluster_size: int = 3
    min_charters_for_pattern: int = 2
    similarity_threshold: float = 0.75
    decay_factor: float = 0.9
    decay_interval_days: int = 30
    revalidation_threshold: float = 0.3
    min_confidence_for_injection: float = 0.5
    max_patterns_per_query: int = 5

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if (
            "consolidation_interval_hours" not in data
            and "consolidation_interval_cycles" in data
        ):
            data = dict(data)
            data["consolidation_interval_hours"] = data["consolidation_interval_cycles"]
        return data


def load_memory_policy(raw_policy: dict[str, Any]) -> MemoryPolicyConfig:
    """Parse the 'memory' section from policy YAML."""
    section = raw_policy.get("memory", {})
    return MemoryPolicyConfig.model_validate(section)
