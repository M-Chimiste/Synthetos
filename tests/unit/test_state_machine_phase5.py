"""Tests for Phase 5 state machine additions (loop_deciding state)."""

from __future__ import annotations

import pytest

from libs.core.state_machine import (
    InvalidTransitionError,
    get_allowed_transitions,
    validate_transition,
)
from libs.core.types import CycleStatus


class TestLoopDecidingTransitions:
    """Verify the new loop_deciding state and its transitions."""

    def test_verifying_to_loop_deciding_allowed(self) -> None:
        validate_transition(CycleStatus.verifying, CycleStatus.loop_deciding)

    def test_loop_deciding_to_running_allowed(self) -> None:
        validate_transition(CycleStatus.loop_deciding, CycleStatus.running)

    def test_loop_deciding_to_reporting_allowed(self) -> None:
        validate_transition(CycleStatus.loop_deciding, CycleStatus.reporting)

    def test_loop_deciding_to_closed_not_allowed(self) -> None:
        with pytest.raises(InvalidTransitionError):
            validate_transition(CycleStatus.loop_deciding, CycleStatus.closed)

    def test_loop_deciding_to_verifying_not_allowed(self) -> None:
        with pytest.raises(InvalidTransitionError):
            validate_transition(CycleStatus.loop_deciding, CycleStatus.verifying)

    def test_running_to_loop_deciding_allowed(self) -> None:
        validate_transition(CycleStatus.running, CycleStatus.loop_deciding)

    def test_reporting_to_loop_deciding_not_allowed(self) -> None:
        with pytest.raises(InvalidTransitionError):
            validate_transition(CycleStatus.reporting, CycleStatus.loop_deciding)

    def test_reporting_to_reporting_allowed(self) -> None:
        validate_transition(CycleStatus.reporting, CycleStatus.reporting)

    def test_get_allowed_from_loop_deciding(self) -> None:
        allowed = get_allowed_transitions(CycleStatus.loop_deciding)
        assert set(allowed) == {CycleStatus.running, CycleStatus.reporting}

    def test_get_allowed_from_verifying_includes_loop_deciding(self) -> None:
        allowed = get_allowed_transitions(CycleStatus.verifying)
        assert CycleStatus.loop_deciding in allowed


class TestExistingTransitionsUnchanged:
    """Ensure Phase 0-4 transitions are not broken by Phase 5 additions."""

    def test_verifying_to_reporting_still_allowed(self) -> None:
        validate_transition(CycleStatus.verifying, CycleStatus.reporting)

    def test_verifying_to_running_still_allowed(self) -> None:
        validate_transition(CycleStatus.verifying, CycleStatus.running)

    def test_reporting_to_closed_still_allowed(self) -> None:
        validate_transition(CycleStatus.reporting, CycleStatus.closed)

    def test_closed_to_closed_allowed(self) -> None:
        validate_transition(CycleStatus.closed, CycleStatus.closed)

    def test_running_to_verifying_still_allowed(self) -> None:
        validate_transition(CycleStatus.running, CycleStatus.verifying)

    def test_created_to_discovery_ready_still_allowed(self) -> None:
        validate_transition(CycleStatus.created, CycleStatus.discovery_ready)


class TestLoopDecidingEnumValue:
    """Verify the loop_deciding enum is correctly defined."""

    def test_loop_deciding_value(self) -> None:
        assert CycleStatus.loop_deciding == "loop_deciding"
        assert CycleStatus.loop_deciding.value == "loop_deciding"

    def test_loop_deciding_in_cycle_status(self) -> None:
        assert hasattr(CycleStatus, "loop_deciding")
