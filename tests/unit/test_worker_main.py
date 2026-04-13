"""Worker helper tests."""

from __future__ import annotations

from datetime import UTC, datetime

from uuid_utils import uuid7

import apps.worker.main as worker_main
from libs.core.types import CycleStatus
from libs.storage.models.analysis import AnalysisSession
from libs.storage.models.discovery import DiscoverySession
from libs.storage.models.jobs import Job
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


def test_mark_discovery_job_failed_marks_session(monkeypatch) -> None:
    job = Job(
        id=uuid7(),
        cycle_id=uuid7(),
        job_type="discovery_finalize",
        status="failed",
        payload={"session_id": str(uuid7())},
        result=None,
        error=None,
        claimed_by=None,
        claimed_at=None,
        heartbeat_at=None,
        priority=0,
        created_at=datetime.now(UTC),
        completed_at=None,
    )
    discovery = DiscoverySession(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
        profile_id=uuid7(),
        status="running",
        view="both",
        stats={},
        step_log=[],
        report_artifact_path=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=None,
    )
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(worker_main, "session_id_from_payload", lambda _input: discovery.id)
    monkeypatch.setattr(worker_main, "load_session", lambda _session, _session_id: discovery)

    def fake_mark_failed(_discovery, *, step: str, error: str, detail: dict[str, str]) -> bool:
        calls.append((step, error))
        assert detail["job_type"] == "discovery_finalize"
        return True

    monkeypatch.setattr(worker_main, "mark_failed", fake_mark_failed)

    session_id, changed = worker_main._mark_discovery_job_failed(
        object(),
        job=job,
        error="report write failed",
    )

    assert changed is True
    assert session_id == discovery.id
    assert calls == [("finalize", "report write failed")]


def test_mark_analysis_job_failed_marks_session(monkeypatch) -> None:
    job = Job(
        id=uuid7(),
        cycle_id=uuid7(),
        job_type="analysis_review",
        status="failed",
        payload={"analysis_session_id": str(uuid7())},
        result=None,
        error=None,
        claimed_by=None,
        claimed_at=None,
        heartbeat_at=None,
        priority=0,
        created_at=datetime.now(UTC),
        completed_at=None,
    )
    analysis = AnalysisSession(
        id=uuid7(),
        cycle_id=uuid7(),
        charter_id=uuid7(),
        paper_card_id=uuid7(),
        status="reviewing",
        budget={},
        stats={},
        step_log=[],
        report_artifact_path=None,
        error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=None,
    )
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        worker_main,
        "analysis_session_id_from_payload",
        lambda _input: analysis.id,
    )
    monkeypatch.setattr(
        worker_main,
        "load_analysis_session",
        lambda _session, _session_id: analysis,
    )

    def fake_mark_analysis_failed(
        _analysis, *, step: str, error: str, detail: dict[str, str]
    ) -> bool:
        calls.append((step, error))
        assert detail["job_type"] == "analysis_review"
        return True

    monkeypatch.setattr(
        worker_main,
        "mark_analysis_failed",
        fake_mark_analysis_failed,
    )

    session_id, paper_card_id, changed = worker_main._mark_analysis_job_failed(
        object(),
        job=job,
        error="report write failed",
    )

    assert changed is True
    assert session_id == analysis.id
    assert paper_card_id == analysis.paper_card_id
    assert calls == [("review", "report write failed")]
