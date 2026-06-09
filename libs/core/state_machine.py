"""Cycle state machine enforcing allowed transitions."""

from __future__ import annotations

from libs.core.types import CycleStatus

# Directed graph of allowed state transitions
ALLOWED_TRANSITIONS: dict[CycleStatus, list[CycleStatus]] = {
    CycleStatus.created: [CycleStatus.discovery_ready],
    CycleStatus.discovery_ready: [CycleStatus.discovery_screened],
    CycleStatus.discovery_screened: [CycleStatus.analysis_ready],
    CycleStatus.analysis_ready: [CycleStatus.analysis_ready, CycleStatus.evidence_ready],
    CycleStatus.evidence_ready: [CycleStatus.portfolio_ready],
    CycleStatus.portfolio_ready: [CycleStatus.protocol_ready],
    CycleStatus.protocol_ready: [CycleStatus.running],
    CycleStatus.running: [
        CycleStatus.verifying,
        CycleStatus.running,
        CycleStatus.loop_deciding,
    ],
    CycleStatus.verifying: [
        CycleStatus.reporting,
        CycleStatus.running,  # retry or next experiment
        CycleStatus.loop_deciding,  # autonomous mode
    ],
    CycleStatus.loop_deciding: [
        CycleStatus.running,  # continue/vary/pivot
        CycleStatus.reporting,  # stop (budget, gate, halt, exhausted)
    ],
    CycleStatus.reporting: [
        CycleStatus.reporting,
        CycleStatus.closed,
    ],
    CycleStatus.closed: [CycleStatus.closed],
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: CycleStatus, target: CycleStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current.value} to {target.value}")


def validate_transition(current: CycleStatus, target: CycleStatus) -> None:
    """Validate that a state transition is allowed.

    Raises InvalidTransitionError if the transition is not permitted.
    """
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidTransitionError(current, target)


def get_allowed_transitions(current: CycleStatus) -> list[CycleStatus]:
    """Return the list of states reachable from the current state."""
    return list(ALLOWED_TRANSITIONS.get(current, []))
