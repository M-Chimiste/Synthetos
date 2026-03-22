from __future__ import annotations

from enum import StrEnum


class CyclePhase(StrEnum):
    """Advisory sub-phase tracker stored in state snapshot context.

    These are NOT state machine states — the cycle still uses CycleStatus
    for state transitions. CyclePhase tracks which logical stage of the
    research pipeline the cycle is in.
    """

    INITIALIZED = "initialized"
    INTAKE_RETRIEVAL = "intake_retrieval"
    INTAKE_SCREENING = "intake_screening"
    INTAKE_SHORTLISTING = "intake_shortlisting"
    INTAKE_ESCALATION = "intake_escalation"
    INTAKE_REPORTING = "intake_reporting"
    INTAKE_COMPLETE = "intake_complete"
