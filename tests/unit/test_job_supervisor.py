"""Tests for the JobSupervisor (heartbeat + cancel polling + deadline watchdog)."""

from __future__ import annotations

import time
from datetime import timedelta

from uuid_utils import uuid7

import apps.worker.heartbeat as heartbeat_module
from apps.worker.heartbeat import JobSupervisor
from libs.core.clock import utcnow
from libs.core.run_context import CancelReason, CancelToken


class _FakeSessionFactory:
    """Context-manager session factory; the session itself is unused because
    heartbeat_job is monkeypatched."""

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _run_supervisor_until(
    monkeypatch,
    *,
    heartbeat_result: tuple[str | None, bool],
    token: CancelToken,
    deadline_s: float | None = None,
    started_at=None,
    condition,
    timeout_s: float = 3.0,
    interval: float = 0.05,
) -> int:
    beats = 0

    def fake_heartbeat_job(_session, _job_id):
        nonlocal beats
        beats += 1
        return heartbeat_result

    monkeypatch.setattr(heartbeat_module, "heartbeat_job", fake_heartbeat_job)

    supervisor = JobSupervisor(
        _FakeSessionFactory(),  # type: ignore[arg-type]
        uuid7(),
        token=token,
        deadline_s=deadline_s,
        started_at=started_at,
        grace_s=0.01,
        interval=interval,
    )
    supervisor.start()
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            if condition():
                break
            time.sleep(0.02)
    finally:
        supervisor.stop()
    return beats


def test_cancel_requested_trips_token_within_one_tick(monkeypatch) -> None:
    token = CancelToken()
    _run_supervisor_until(
        monkeypatch,
        heartbeat_result=("running", True),
        token=token,
        condition=lambda: token.cancelled,
    )
    assert token.cancelled
    assert token.reason == CancelReason.user_cancel


def test_legacy_cancelled_status_trips_token(monkeypatch) -> None:
    token = CancelToken()
    _run_supervisor_until(
        monkeypatch,
        heartbeat_result=("cancelled", False),
        token=token,
        condition=lambda: token.cancelled,
    )
    assert token.cancelled
    assert token.reason == CancelReason.user_cancel


def test_deadline_overrun_trips_token_with_timeout_reason(monkeypatch) -> None:
    token = CancelToken()
    _run_supervisor_until(
        monkeypatch,
        heartbeat_result=("running", False),
        token=token,
        deadline_s=0.01,
        started_at=utcnow() - timedelta(seconds=10),
        condition=lambda: token.cancelled,
    )
    assert token.cancelled
    assert token.reason == CancelReason.timeout


def test_heartbeats_continue_after_token_trips(monkeypatch) -> None:
    """Reclaim during in-process execution would double-run the job, so the
    supervisor must keep heartbeating after signalling cancellation."""
    token = CancelToken()
    beat_counts: list[int] = []

    beats = _run_supervisor_until(
        monkeypatch,
        heartbeat_result=("running", True),
        token=token,
        condition=lambda: beat_counts.append(0) or len(beat_counts) > 60,
        timeout_s=1.0,
        interval=0.02,
    )
    assert token.cancelled
    assert beats >= 3  # kept beating well past the cancel signal


def test_healthy_job_never_trips_token(monkeypatch) -> None:
    token = CancelToken()
    _run_supervisor_until(
        monkeypatch,
        heartbeat_result=("running", False),
        token=token,
        deadline_s=3600,
        condition=lambda: False,
        timeout_s=0.3,
    )
    assert not token.cancelled
