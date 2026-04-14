"""Focused tests for stale job reclaim behavior."""

from __future__ import annotations

from dataclasses import dataclass

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

    assert counts == {"reclaimed": 1, "failed_exhausted": 0}
    assert job.status == JobStatus.pending
    assert job.reclaim_count == 1
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

    assert counts == {"reclaimed": 0, "failed_exhausted": 1}
    assert job.status == JobStatus.failed
    assert "reclaim_exhausted" in (job.error or "")
    assert session.committed is True
    assert events == ["job.reclaim_exhausted"]
