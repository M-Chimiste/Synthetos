"""Focused tests for stale job reclaim behavior."""

from __future__ import annotations

from dataclasses import dataclass, field

from uuid_utils import uuid7

from libs.core.services import job_service
from libs.core.types import JobStatus


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self):
        return self._rows


@dataclass
class _Job:
    id: object
    cycle_id: object
    job_type: str
    status: str
    reclaim_count: int = 0
    claimed_at: object | None = None
    heartbeat_at: object | None = None
    claimed_by: str | None = "worker"
    completed_at: object | None = None
    error: str | None = None
    error_detail: dict | None = None
    started_at: object | None = None
    not_before: object | None = None
    cancel_requested: bool = False
    attempt_count: int = 0
    max_attempts: int = 3
    payload: dict = field(default_factory=dict)


class _Session:
    def __init__(self, jobs):
        self.jobs = jobs
        self.committed = False

    def execute(self, _stmt):
        return _ScalarResult(self.jobs)

    def commit(self) -> None:
        self.committed = True


def test_reclaim_stale_jobs_requeues_running_work(monkeypatch) -> None:
    job = _Job(
        id=uuid7(),
        cycle_id=uuid7(),
        job_type="analysis_ingest",
        status=JobStatus.running,
        reclaim_count=0,
    )
    session = _Session([job])
    events: list[str] = []

    monkeypatch.setattr(
        job_service,
        "emit_event_sync",
        lambda _session, *, event_type, **_kwargs: events.append(event_type),
    )

    counts = job_service.reclaim_stale_jobs(
        session,
        heartbeat_timeout_s=120,
        max_reclaims=3,
    )

    assert counts == {"reclaimed": 1, "failed_exhausted": 0, "cancelled": 0}
    assert job.status == JobStatus.pending
    assert job.reclaim_count == 1
    # Requeue carries a short delay to damp crash-loops on a poison job.
    assert job.not_before is not None
    assert job.started_at is None
    assert session.committed is True
    assert events == ["job.reclaimed"]


def test_reclaim_stale_jobs_fails_exhausted_work(monkeypatch) -> None:
    job = _Job(
        id=uuid7(),
        cycle_id=uuid7(),
        job_type="execution_run",
        status=JobStatus.claimed,
        reclaim_count=3,
    )
    session = _Session([job])
    events: list[str] = []

    monkeypatch.setattr(
        job_service,
        "emit_event_sync",
        lambda _session, *, event_type, **_kwargs: events.append(event_type),
    )

    counts = job_service.reclaim_stale_jobs(
        session,
        heartbeat_timeout_s=120,
        max_reclaims=3,
    )

    assert counts == {"reclaimed": 0, "failed_exhausted": 1, "cancelled": 0}
    assert job.status == JobStatus.failed
    assert "reclaim_exhausted" in (job.error or "")
    assert (job.error_detail or {}).get("error_class") == "reclaim_exhausted"
    assert session.committed is True
    assert events == ["job.reclaim_exhausted"]


def test_reclaim_honors_pending_cancel_request(monkeypatch) -> None:
    """A stale job whose user requested cancel is cancelled, not requeued."""
    job = _Job(
        id=uuid7(),
        cycle_id=uuid7(),
        job_type="analysis_ingest",
        status=JobStatus.running,
        cancel_requested=True,
    )
    session = _Session([job])
    events: list[str] = []

    monkeypatch.setattr(
        job_service,
        "emit_event_sync",
        lambda _session, *, event_type, **_kwargs: events.append(event_type),
    )

    counts = job_service.reclaim_stale_jobs(
        session,
        heartbeat_timeout_s=120,
        max_reclaims=3,
    )

    assert counts == {"reclaimed": 0, "failed_exhausted": 0, "cancelled": 1}
    assert job.status == JobStatus.cancelled
    assert job.cancel_requested is False
    assert job.completed_at is not None
    assert events == ["job_cancelled_acknowledged"]
