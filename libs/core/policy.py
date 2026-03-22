from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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

