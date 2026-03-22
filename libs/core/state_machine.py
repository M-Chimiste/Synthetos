from __future__ import annotations

from enum import StrEnum


class CycleStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    INITIALIZING = "initializing"
    READY = "ready"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"


ALLOWED_TRANSITIONS: dict[CycleStatus, set[CycleStatus]] = {
    CycleStatus.CREATED: {CycleStatus.QUEUED, CycleStatus.CANCELLED, CycleStatus.FAILED},
    CycleStatus.QUEUED: {
        CycleStatus.INITIALIZING,
        CycleStatus.PAUSED,
        CycleStatus.CANCEL_REQUESTED,
        CycleStatus.CANCELLED,
        CycleStatus.FAILED,
    },
    CycleStatus.INITIALIZING: {
        CycleStatus.READY,
        CycleStatus.PAUSED,
        CycleStatus.CANCEL_REQUESTED,
        CycleStatus.FAILED,
    },
    CycleStatus.READY: {
        CycleStatus.QUEUED,
        CycleStatus.PAUSED,
        CycleStatus.CANCEL_REQUESTED,
        CycleStatus.CANCELLED,
    },
    CycleStatus.PAUSED: {CycleStatus.QUEUED, CycleStatus.READY, CycleStatus.CANCEL_REQUESTED},
    CycleStatus.CANCEL_REQUESTED: {CycleStatus.CANCELLED, CycleStatus.FAILED},
    CycleStatus.CANCELLED: set(),
    CycleStatus.FAILED: {CycleStatus.QUEUED, CycleStatus.CANCELLED},
}


def ensure_transition(current: CycleStatus, target: CycleStatus) -> None:
    if current == target:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"Invalid cycle transition: {current} -> {target}")

