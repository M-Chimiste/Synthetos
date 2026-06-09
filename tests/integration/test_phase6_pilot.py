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

from libs.core.clock import utcnow
from libs.core.services import discovery_service
from libs.pilot import runner as pilot_runner
from libs.pilot.fixture import load_fixture
from libs.schemas.discovery import DiscoverySessionRead
from libs.storage.models.discovery import DiscoverySession

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


async def test_discovery_kickoff_accepts_uuid_utils_cycle_charter_id(monkeypatch) -> None:
    charter_id = UUID(str(uuid7()))
    cycle_id = UUID(str(uuid7()))
    cycle = SimpleNamespace(id=cycle_id, charter_id=uuid7())
    cycle.charter_id = type(cycle.charter_id)(str(charter_id))
    charter = SimpleNamespace(id=charter_id)
    captured: dict[str, object] = {}

    class FakeAsyncSession:
        async def get(self, model, key):
            if model.__name__ == "ResearchCharter" and str(key) == str(charter_id):
                return charter
            if model.__name__ == "ResearchCycle" and str(key) == str(cycle_id):
                return cycle
            return None

    async def fake_start(session, *, charter_id, cycle, body, actor_type, actor_id):
        captured["charter_id"] = charter_id
        captured["cycle"] = cycle
        return SimpleNamespace(), SimpleNamespace(), uuid7()

    monkeypatch.setattr(
        discovery_service,
        "_start_discovery_session_on_cycle",
        fake_start,
    )

    _session, _profile, job_id = await discovery_service.start_discovery_session_for_cycle(
        FakeAsyncSession(),
        charter_id=charter_id,
        cycle_id=cycle_id,
        body=SimpleNamespace(),
    )

    assert job_id is not None
    assert captured["charter_id"] == charter_id
    assert captured["cycle"] is cycle


def test_discovery_read_model_normalizes_uuid_utils_ids() -> None:
    now = utcnow()
    row = DiscoverySession(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
        profile_id=uuid7(),
        status="created",
        view="both",
        stats={},
        step_log=[],
        created_at=now,
        updated_at=now,
    )

    read = discovery_service._read_model(DiscoverySessionRead, row)

    assert isinstance(read.id, UUID)
    assert isinstance(read.charter_id, UUID)
    assert read.status == "created"


def test_pilot_discovery_profile_uses_reference_sources_as_derived_query() -> None:
    fixture = load_fixture(FIXTURE_ROOT / "diffusionblocks_e2e")

    profile = pilot_runner._discovery_profile(fixture)

    hints = profile.source_scope["search_hints"]
    assert hints["derived_query"] == "https://arxiv.org/html/2506.14202v3"
