"""Tests for LLM call transcript persistence."""

from __future__ import annotations

import pytest

from libs.adapters.llm.reliability import LLMCallRecord
from libs.core.services import llm_call_service


class _CaptureSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def __enter__(self) -> _CaptureSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True


@pytest.fixture
def capture_session(monkeypatch) -> _CaptureSession:
    session = _CaptureSession()
    monkeypatch.setattr(
        llm_call_service, "get_sync_session_factory", lambda *a, **k: lambda: session
    )
    return session


def _record(**overrides) -> LLMCallRecord:
    defaults = dict(
        role="evaluation",
        provider="local",
        model="test-model",
        base_url="http://local.test/v1",
        request_kind="structured",
        response_model="TinyResponse",
        messages=[{"role": "user", "content": "ping"}],
        outcome="success",
        attempts=2,
        latency_ms=1234,
        response_text="x" * 50,
        finish_reason="stop",
        input_tokens=10,
        output_tokens=5,
    )
    defaults.update(overrides)
    return LLMCallRecord(**defaults)


def _force_settings(monkeypatch, **values) -> None:
    settings = llm_call_service.get_settings()
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


def test_record_stores_hash_only_by_default(monkeypatch, capture_session) -> None:
    _force_settings(
        monkeypatch, llm_call_logging_enabled=True, llm_log_prompts=False
    )
    llm_call_service.record_llm_call_sync(_record())

    assert capture_session.committed
    assert len(capture_session.added) == 1
    row = capture_session.added[0]
    assert row.messages is None  # prompts not stored by default
    assert row.response_text is None
    assert len(row.messages_hash) == 64  # sha256 hex
    assert row.outcome == "success"
    assert row.attempts == 2
    assert row.latency_ms == 1234


def test_record_stores_full_prompts_when_enabled(monkeypatch, capture_session) -> None:
    _force_settings(
        monkeypatch,
        llm_call_logging_enabled=True,
        llm_log_prompts=True,
        llm_log_max_response_chars=20,
    )
    llm_call_service.record_llm_call_sync(_record(response_text="y" * 100))

    row = capture_session.added[0]
    assert row.messages == [{"role": "user", "content": "ping"}]
    assert row.response_text == "y" * 20  # capped


def test_record_disabled_writes_nothing(monkeypatch, capture_session) -> None:
    _force_settings(monkeypatch, llm_call_logging_enabled=False)
    llm_call_service.record_llm_call_sync(_record())
    assert capture_session.added == []


def test_recorder_failure_is_swallowed(monkeypatch) -> None:
    _force_settings(monkeypatch, llm_call_logging_enabled=True)

    def exploding_factory(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        llm_call_service, "get_sync_session_factory", exploding_factory
    )
    # Must not raise: telemetry never fails the call it describes.
    llm_call_service.record_llm_call_sync(_record())


@pytest.mark.asyncio
async def test_async_wrapper_runs_sync_writer(monkeypatch, capture_session) -> None:
    _force_settings(monkeypatch, llm_call_logging_enabled=True)
    await llm_call_service.record_llm_call(_record())
    assert capture_session.committed
