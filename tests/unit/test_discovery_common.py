"""Tests for shared discovery operator helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from uuid_utils import uuid7

from libs.discovery.operators._common import mark_failed
from libs.storage.models.discovery import DiscoverySession


def _session() -> DiscoverySession:
    now = datetime.now(UTC)
    return DiscoverySession(
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
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=None,
    )


def test_mark_failed_sets_status_and_step_log() -> None:
    discovery = _session()

    changed = mark_failed(
        discovery,
        step="finalize",
        error="report write failed",
        detail={"report_path": None},
    )

    assert changed is True
    assert discovery.status == "failed"
    assert discovery.error == "report write failed"
    assert discovery.completed_at is not None
    assert discovery.step_log is not None
    assert discovery.step_log[-1]["status"] == "failed"
    assert discovery.step_log[-1]["detail"]["error"] == "report write failed"


def test_mark_failed_is_idempotent_for_same_error() -> None:
    discovery = _session()
    mark_failed(discovery, step="search", error="boom")
    first_log_len = len(discovery.step_log or [])

    changed = mark_failed(discovery, step="search", error="boom")

    assert changed is False
    assert len(discovery.step_log or []) == first_log_len
