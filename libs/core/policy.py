from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


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

