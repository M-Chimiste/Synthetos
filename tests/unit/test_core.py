from libs.core.ids import generate_public_id
from libs.core.state_machine import CycleStatus, ensure_transition


def test_generate_public_id_uses_prefix() -> None:
    public_id = generate_public_id("cycle")
    assert public_id.startswith("cycle_")


def test_state_machine_allows_phase0_path() -> None:
    ensure_transition(CycleStatus.CREATED, CycleStatus.QUEUED)
    ensure_transition(CycleStatus.QUEUED, CycleStatus.INITIALIZING)
    ensure_transition(CycleStatus.INITIALIZING, CycleStatus.READY)

