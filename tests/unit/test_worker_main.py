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


def test_apply_state_patch_ignores_nonterminal_patch_for_closed_cycle(monkeypatch) -> None:
    completed_at = datetime.now(UTC)
    cycle = ResearchCycle(
        id=uuid7(),
        charter_id=uuid7(),
        status=CycleStatus.closed,
        config=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=completed_at,
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
        state_patch={"target_status": CycleStatus.reporting.value},
        worker_id="worker-1",
    )

    assert cycle.status == CycleStatus.closed
    assert cycle.completed_at == completed_at
    assert emitted == []


def test_apply_state_patch_walks_allowed_intermediate_states(monkeypatch) -> None:
    cycle = ResearchCycle(
        id=uuid7(),
        charter_id=uuid7(),
        status=CycleStatus.portfolio_ready,
        config=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
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
        state_patch={"target_status": CycleStatus.verifying.value},
        worker_id="worker-1",
    )

    assert cycle.status == CycleStatus.verifying
    assert [event["payload"] for event in emitted] == [
        {"from_status": "portfolio_ready", "to_status": "protocol_ready"},
        {"from_status": "protocol_ready", "to_status": "running"},
        {"from_status": "running", "to_status": "verifying"},
    ]


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


def test_goal_advance_failure_predicate_covers_pre_run_failures() -> None:
    cycle_id = uuid7()

    def job(job_type: str, *, cycle=True) -> Job:
        return Job(
            id=uuid7(),
            cycle_id=cycle_id if cycle else None,
            job_type=job_type,
            status="failed",
            payload={},
            result=None,
            error=None,
            claimed_by=None,
            claimed_at=None,
            heartbeat_at=None,
            priority=0,
            created_at=datetime.now(UTC),
            completed_at=None,
        )

    assert worker_main._should_enqueue_goal_advance_after_failure(job("analysis_chunk"))
    assert worker_main._should_enqueue_goal_advance_after_failure(job("hypothesis_generate"))
    assert worker_main._should_enqueue_goal_advance_after_failure(job("protocol_compile"))
    assert not worker_main._should_enqueue_goal_advance_after_failure(job("execution_run"))
    assert not worker_main._should_enqueue_goal_advance_after_failure(
        job("analysis_chunk", cycle=False)
    )


# ---------------------------------------------------------------------------
# _handle_failure branch tests
# ---------------------------------------------------------------------------

from libs.core.errors import ErrorClass  # noqa: E402
from libs.core.operators import OperatorFailure, OperatorResult  # noqa: E402
from libs.core.types import JobStatus  # noqa: E402


class _CommitSession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


def _failed_job(job_type: str = "analysis_chunk", *, status: str = JobStatus.running) -> Job:
    return Job(
        id=uuid7(),
        cycle_id=uuid7(),
        job_type=job_type,
        status=status,
        payload={},
        result=None,
        error=None,
        claimed_by="worker-1",
        claimed_at=datetime.now(UTC),
        heartbeat_at=None,
        priority=0,
        created_at=datetime.now(UTC),
        completed_at=None,
    )


def _failure_result(error_class: ErrorClass, error: str = "boom") -> OperatorResult:
    return OperatorResult(
        success=False,
        error=error,
        failure=OperatorFailure(
            error_class=error_class,
            exc_type="TestError",
            traceback="Traceback: boom",
        ),
    )


def _patch_failure_handlers(monkeypatch, events: list[str]) -> dict[str, list]:
    calls: dict[str, list] = {
        "cancel": [],
        "retry": [],
        "mark": [],
        "goal_advance": [],
    }

    monkeypatch.setattr(
        worker_main,
        "emit_event_sync",
        lambda _s, *, event_type, **_k: events.append(event_type),
    )

    def fake_cancel(_s, job_id, *, error_detail=None):
        calls["cancel"].append(job_id)

    monkeypatch.setattr(worker_main, "cancel_job_record", fake_cancel)

    def fake_mark(_s, *, job, error):
        calls["mark"].append(job.job_type)
        return None, False

    monkeypatch.setattr(worker_main, "_mark_discovery_job_failed", fake_mark)
    monkeypatch.setattr(
        worker_main, "_mark_analysis_job_failed", lambda _s, *, job, error: (None, None, False)
    )
    monkeypatch.setattr(worker_main, "_mark_ideation_job_failed", fake_mark)
    monkeypatch.setattr(worker_main, "_mark_execution_job_failed", fake_mark)

    def fake_goal_advance(_s, **kwargs):
        calls["goal_advance"].append(kwargs)

    monkeypatch.setattr(worker_main, "_enqueue_goal_advance_after_failure", fake_goal_advance)
    return calls


def test_handle_failure_cancelled_skips_failure_side_effects(monkeypatch) -> None:
    events: list[str] = []
    calls = _patch_failure_handlers(monkeypatch, events)
    job = _failed_job()
    session = _CommitSession()

    worker_main._handle_failure(
        session,
        job=job,
        result=_failure_result(ErrorClass.cancelled),
        charter_id=None,
        worker_id="worker-1",
    )

    assert calls["cancel"] == [job.id]
    assert "job_cancelled_acknowledged" in events
    assert "job_failed" not in events
    assert calls["mark"] == []
    assert calls["goal_advance"] == []
    assert session.committed


def test_handle_failure_transient_schedules_retry(monkeypatch) -> None:
    events: list[str] = []
    calls = _patch_failure_handlers(monkeypatch, events)
    job = _failed_job()
    session = _CommitSession()

    def fake_retry(_s, _job_id, *, error, error_detail, retryable):
        assert retryable is True
        job.status = JobStatus.pending
        job.attempt_count = 1
        job.max_attempts = 3
        return job

    monkeypatch.setattr(worker_main, "retry_or_fail_job", fake_retry)

    worker_main._handle_failure(
        session,
        job=job,
        result=_failure_result(ErrorClass.transient),
        charter_id=None,
        worker_id="worker-1",
    )

    assert "job.retry_scheduled" in events
    assert "job.attempt_failed" in events
    assert "job_failed" not in events
    assert calls["mark"] == []  # downstream state untouched on retry
    assert calls["goal_advance"] == []
    assert session.committed


def test_handle_failure_final_runs_side_effects(monkeypatch) -> None:
    events: list[str] = []
    calls = _patch_failure_handlers(monkeypatch, events)
    job = _failed_job()
    session = _CommitSession()

    def fake_retry(_s, _job_id, *, error, error_detail, retryable):
        assert retryable is False  # permanent
        job.status = JobStatus.failed
        return job

    monkeypatch.setattr(worker_main, "retry_or_fail_job", fake_retry)

    worker_main._handle_failure(
        session,
        job=job,
        result=_failure_result(ErrorClass.permanent),
        charter_id=None,
        worker_id="worker-1",
    )

    assert "job_failed" in events
    assert len(calls["mark"]) == 3  # discovery/ideation/execution markers ran
    assert calls["goal_advance"] != []  # analysis_chunk is goal-advance eligible
    assert session.committed


def test_handle_failure_goal_advance_raise_does_not_abort(monkeypatch) -> None:
    events: list[str] = []
    _patch_failure_handlers(monkeypatch, events)
    job = _failed_job()
    session = _CommitSession()

    def fake_retry(_s, _job_id, *, error, error_detail, retryable):
        job.status = JobStatus.failed
        return job

    monkeypatch.setattr(worker_main, "retry_or_fail_job", fake_retry)

    def exploding_goal_advance(_s, **kwargs):
        raise RuntimeError("goal service down")

    monkeypatch.setattr(worker_main, "_enqueue_goal_advance_after_failure", exploding_goal_advance)

    worker_main._handle_failure(
        session,
        job=job,
        result=_failure_result(ErrorClass.permanent),
        charter_id=None,
        worker_id="worker-1",
    )

    assert "job_failed" in events  # still emitted despite the raise
    assert session.committed


def test_handle_failure_paused_job_stays_paused(monkeypatch) -> None:
    events: list[str] = []
    calls = _patch_failure_handlers(monkeypatch, events)
    job = _failed_job(status=JobStatus.paused)
    session = _CommitSession()
    retry_called: list[bool] = []

    monkeypatch.setattr(
        worker_main,
        "retry_or_fail_job",
        lambda *_a, **_k: retry_called.append(True),
    )

    worker_main._handle_failure(
        session,
        job=job,
        result=_failure_result(ErrorClass.transient),
        charter_id=None,
        worker_id="worker-1",
    )

    assert job.status == JobStatus.paused
    assert retry_called == []  # no retry scheduling for a user-paused job
    assert "job.attempt_failed" in events
    assert "job_failed" not in events
    assert job.error == "boom"
    assert calls["mark"] == []
