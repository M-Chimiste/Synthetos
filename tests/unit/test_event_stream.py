"""SSE streaming contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from uuid_utils import uuid7

from apps.api.routers.events import _event_stream
from libs.core.types import ActorType
from libs.storage.models.events import DomainEvent


class _FakeScalarResult:
    def __init__(self, events: list[DomainEvent]) -> None:
        self._events = events

    def scalars(self) -> _FakeScalarResult:
        return self

    def all(self) -> list[DomainEvent]:
        return self._events


class _FakeAsyncSession:
    def __init__(self, batches: list[list[DomainEvent]]) -> None:
        self._batches = list(batches)

    async def execute(self, _query: object) -> _FakeScalarResult:
        if self._batches:
            return _FakeScalarResult(self._batches.pop(0))
        return _FakeScalarResult([])


@pytest.mark.asyncio
async def test_event_stream_emits_default_message_frames() -> None:
    event = DomainEvent(
        id=UUID(str(uuid7())),
        charter_id=UUID(str(uuid7())),
        cycle_id=None,
        event_type="job_completed",
        payload={"job_id": "abc"},
        actor_type=ActorType.worker,
        actor_id="worker-1",
        created_at=datetime.now(UTC),
    )
    stream = _event_stream(
        _FakeAsyncSession([[event]]),
        charter_id=None,
        cycle_id=None,
        last_event_id=None,
    )

    frame = await anext(stream)
    await stream.aclose()

    assert frame.startswith(f"id: {event.id}\ndata: ")
    assert "\nevent:" not in frame
    assert '"event_type": "job_completed"' in frame
