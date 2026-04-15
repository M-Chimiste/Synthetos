"""Focused Phase 6 pilot kickoff integration tests.

These tests stay hermetic by faking the DB/session boundaries, but they drive
the public pilot runner entry point end to end: fixture load -> charter/cycle
creation -> discovery kickoff scheduling.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from uuid_utils import uuid7

from libs.pilot import runner as pilot_runner
from libs.pilot.fixture import load_fixture

FIXTURE_ROOT = Path("configs/problems")


class _FakePilotSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


class _Factory:
    def __init__(self, session: _FakePilotSession) -> None:
        self._session = session

    def __call__(self) -> _Factory:
        return self

    def __enter__(self) -> _FakePilotSession:
        return self._session

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_start_pilot_creates_cycle_and_kicks_off_discovery(monkeypatch) -> None:
    fixture = load_fixture(FIXTURE_ROOT / "ml_baseline_small")
    session = _FakePilotSession()
    charter = SimpleNamespace(id=uuid7(), source_scope=None)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        pilot_runner,
        "_upsert_charter",
        lambda _db, _fixture: charter,
    )
    monkeypatch.setattr(
        pilot_runner,
        "get_sync_session_factory",
        lambda: _Factory(session),
    )

    async def fake_kickoff(*, charter_id: UUID, cycle_id: UUID, fixture) -> UUID:
        captured["charter_id"] = charter_id
        captured["cycle_id"] = cycle_id
        captured["problem_id"] = fixture.problem_id
        return uuid7()

    monkeypatch.setattr(pilot_runner, "_kickoff_discovery", fake_kickoff)

    def fake_run(coro):
        try:
            coro.send(None)
        except StopIteration as exc:
            return exc.value
        raise AssertionError("kickoff coroutine yielded unexpectedly")

    monkeypatch.setattr(pilot_runner.asyncio, "run", fake_run)

    handle = pilot_runner.start_pilot(fixture)

    assert session.committed is True
    assert handle.charter_id == charter.id
    assert captured["charter_id"] == charter.id
    assert captured["cycle_id"] == handle.cycle_id
    assert captured["problem_id"] == fixture.problem_id
    assert any(getattr(obj, "charter_id", None) == charter.id for obj in session.added)
