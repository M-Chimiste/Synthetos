"""Tests for job-level retry scheduling (retry_or_fail_job)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pytest
from uuid_utils import uuid7

from libs.core.clock import utcnow
from libs.core.services import job_service
from libs.core.types import JobStatus


@dataclass
class _Job:
    id: object
    job_type: str = "analysis_ingest"
    status: str = JobStatus.running
    attempt_count: int = 0
    max_attempts: int = 3
    error: str | None = None
    error_detail: dict | None = None
    claimed_by: str | None = "worker"
    claimed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    not_before: datetime | None = None
    cycle_id: object | None = None
    payload: dict = field(default_factory=dict)


class _Session:
    def __init__(self, job: _Job) -> None:
        self._job = job
        self.flushed = False

    def get(self, _model: type[object], key: object) -> _Job | None:
        return self._job if key == self._job.id else None

    def flush(self) -> None:
        self.flushed = True


def test_retryable_failure_requeues_with_backoff() -> None:
    job = _Job(id=uuid7())
    session = _Session(job)
    before = utcnow()

    updated = job_service.retry_or_fail_job(
        session,
        job.id,
        error="connection refused",
        error_detail={"error_class": "transient", "exc_type": "ConnectionError"},
        retryable=True,
    )

    assert updated.status == JobStatus.pending
    assert updated.attempt_count == 1
    assert updated.claimed_by is None
    assert updated.claimed_at is None
    assert updated.heartbeat_at is None
    assert updated.started_at is None
    assert updated.not_before is not None
    # First retry: base 60s with 0.8-1.2 jitter.
    delay = (updated.not_before - before).total_seconds()
    assert 40 <= delay <= 80
    history = (updated.error_detail or {}).get("attempts") or []
    assert len(history) == 1
    assert history[0]["attempt"] == 1
    assert (updated.error_detail or {}).get("exc_type") == "ConnectionError"


def test_backoff_grows_exponentially() -> None:
    job = _Job(id=uuid7(), attempt_count=1, max_attempts=5)
    session = _Session(job)
    before = utcnow()

    updated = job_service.retry_or_fail_job(
        session,
        job.id,
        error="still flaky",
        error_detail=None,
        retryable=True,
    )

    assert updated.attempt_count == 2
    assert updated.not_before is not None
    # Second retry: base 60 * 2^1 = 120s with jitter.
    delay = (updated.not_before - before).total_seconds()
    assert 90 <= delay <= 150


def test_exhausted_attempts_fail_permanently(monkeypatch) -> None:
    job = _Job(id=uuid7(), attempt_count=2, max_attempts=3)
    session = _Session(job)
    failed: dict = {}

    def fake_fail_job(_session, job_id, error, *, error_detail=None):
        failed["job_id"] = job_id
        failed["error"] = error
        failed["error_detail"] = error_detail
        job.status = JobStatus.failed
        return job

    monkeypatch.setattr(job_service, "fail_job", fake_fail_job)

    updated = job_service.retry_or_fail_job(
        session,
        job.id,
        error="third strike",
        error_detail={"error_class": "transient"},
        retryable=True,
    )

    assert updated.status == JobStatus.failed
    assert failed["job_id"] == job.id
    # The failing attempt is recorded in the history.
    history = (failed["error_detail"] or {}).get("attempts") or []
    assert history[-1]["attempt"] == 3


def test_non_retryable_fails_immediately(monkeypatch) -> None:
    job = _Job(id=uuid7(), attempt_count=0, max_attempts=3)
    session = _Session(job)
    called: list[str] = []

    def fake_fail_job(_session, _job_id, error, *, error_detail=None):
        called.append(error)
        job.status = JobStatus.failed
        return job

    monkeypatch.setattr(job_service, "fail_job", fake_fail_job)

    updated = job_service.retry_or_fail_job(
        session,
        job.id,
        error="bad input",
        error_detail={"error_class": "permanent"},
        retryable=False,
    )

    assert updated.status == JobStatus.failed
    assert called == ["bad input"]


def test_attempt_history_is_capped() -> None:
    job = _Job(
        id=uuid7(),
        attempt_count=0,
        max_attempts=50,
        error_detail={"attempts": [{"attempt": i} for i in range(15)]},
    )
    session = _Session(job)

    updated = job_service.retry_or_fail_job(
        session,
        job.id,
        error="flaky",
        error_detail=None,
        retryable=True,
    )

    history = (updated.error_detail or {}).get("attempts") or []
    assert len(history) == 10  # capped


def test_backoff_respects_cap(monkeypatch) -> None:
    job = _Job(id=uuid7(), attempt_count=10, max_attempts=20)
    session = _Session(job)
    before = utcnow()

    updated = job_service.retry_or_fail_job(
        session,
        job.id,
        error="flaky",
        error_detail=None,
        retryable=True,
    )

    assert updated.not_before is not None
    delay = (updated.not_before - before).total_seconds()
    # Cap is 1800s; jitter up to 1.2x applies to the capped value.
    assert delay <= 1800 * 1.2 + 1


def test_missing_job_raises() -> None:
    job = _Job(id=uuid7())
    session = _Session(job)
    with pytest.raises(AssertionError):
        job_service.retry_or_fail_job(
            session,
            uuid7(),  # different id
            error="x",
            error_detail=None,
            retryable=True,
        )
