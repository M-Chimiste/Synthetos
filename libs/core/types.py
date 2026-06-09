"""Core type definitions, ID types, and enums for the Synthetos domain."""

from __future__ import annotations

from enum import StrEnum
from typing import NewType
from uuid import UUID

# --- Identity types ---
# All primary keys use UUIDv7 (time-sortable).
# These NewTypes provide type safety without runtime overhead.

CharterId = NewType("CharterId", UUID)
CycleId = NewType("CycleId", UUID)
JobId = NewType("JobId", UUID)
EventId = NewType("EventId", UUID)
SkillDefId = NewType("SkillDefId", UUID)
OrchestratorClientId = NewType("OrchestratorClientId", UUID)
ApiTokenId = NewType("ApiTokenId", UUID)
ModelCallId = NewType("ModelCallId", UUID)
GoalId = NewType("GoalId", UUID)


# --- Enums ---


class CycleStatus(StrEnum):
    """Allowed states for a ResearchCycle.

    Transitions are enforced by the state machine in libs/core/state_machine.py.
    """

    created = "created"
    discovery_ready = "discovery_ready"
    discovery_screened = "discovery_screened"
    analysis_ready = "analysis_ready"
    evidence_ready = "evidence_ready"
    portfolio_ready = "portfolio_ready"
    protocol_ready = "protocol_ready"
    running = "running"
    verifying = "verifying"
    loop_deciding = "loop_deciding"
    reporting = "reporting"
    closed = "closed"


class CharterStatus(StrEnum):
    """Status of a ResearchCharter."""

    active = "active"
    paused = "paused"
    completed = "completed"
    archived = "archived"


class GoalStatus(StrEnum):
    """Status of a ResearchGoal."""

    created = "created"
    running = "running"
    satisfied = "satisfied"
    exhausted = "exhausted"
    stopped = "stopped"
    failed = "failed"


class JobStatus(StrEnum):
    """Status of a queued job."""

    pending = "pending"
    claimed = "claimed"
    paused = "paused"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ActorType(StrEnum):
    """Who or what caused a domain event."""

    system = "system"
    user = "user"
    orchestrator = "orchestrator"
    worker = "worker"


class TrustTier(StrEnum):
    """Trust tiers for skill packages."""

    first_party_trusted = "first_party_trusted"
    user_local_trusted = "user_local_trusted"
    third_party_untrusted = "third_party_untrusted"
