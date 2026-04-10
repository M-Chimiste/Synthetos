"""Worker helper tests."""

from __future__ import annotations

from datetime import UTC, datetime

from uuid_utils import uuid7

import apps.worker.main as worker_main
from libs.core.types import CycleStatus
from libs.storage.models.research import ResearchCycle


class _FakeSession:
    def __init__(self, cycle: ResearchCycle) -> None:
        self._cycle = cycle

    def get(self, model: type[object], key: object) -> ResearchCycle | None:
        if model is ResearchCycle and key == self._cycle.id:
            return self._cycle
        return None


def test_apply_state_patch_updates_cycle_and_emits_transition(monkeypatch) -> None:
    cycle = ResearchCycle(
        id=uuid7(),
        charter_id=uuid7(),
        status=CycleStatus.created,
        config=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
    )
    session = _FakeSession(cycle)
    emitted: list[dict[str, object]] = []

    def fake_emit_event_sync(session_obj: object, **kwargs: object) -> None:
        emitted.append({"session": session_obj, **kwargs})

    monkeypatch.setattr(worker_main, "emit_event_sync", fake_emit_event_sync)

    worker_main._apply_state_patch(
        session,
        cycle_id=cycle.id,
        charter_id=cycle.charter_id,
        state_patch={"target_status": CycleStatus.discovery_ready.value},
        worker_id="worker-1",
    )

    assert cycle.status == CycleStatus.discovery_ready
    assert cycle.started_at is not None
    assert emitted[0]["event_type"] == "research_cycle_transitioned"


def test_persist_operator_events_writes_each_event(monkeypatch) -> None:
    emitted: list[dict[str, object]] = []

    def fake_emit_event_sync(_session_obj: object, **kwargs: object) -> None:
        emitted.append(kwargs)

    monkeypatch.setattr(worker_main, "emit_event_sync", fake_emit_event_sync)

    worker_main._persist_operator_events(
        object(),
        charter_id=uuid7(),
        cycle_id=uuid7(),
        events=[
            {"event_type": "operator_step_started", "payload": {"step": 1}},
            {"event_type": "operator_step_finished", "payload": {"step": 1}},
        ],
        worker_id="worker-1",
    )

    assert [event["event_type"] for event in emitted] == [
        "operator_step_started",
        "operator_step_finished",
    ]
