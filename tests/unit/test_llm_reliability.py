"""Tests for the LLM reliability layer (retry, truncation, feedback, fallback, cancel)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from libs.adapters.llm.concurrency import EndpointLimiter
from libs.adapters.llm.errors import LLMRetriesExhausted, LLMTransportError
from libs.adapters.llm.openai_compat import OpenAICompatAdapter
from libs.adapters.llm.reliability import LLMCallRecord, ReliableLLMClient, RetryPolicy
from libs.core.errors import OperationCancelled
from libs.core.run_context import CancelReason, CancelToken, JobContext, set_job_context

BASE_URL = "http://primary.test/v1"
FALLBACK_URL = "http://fallback.test/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"
FALLBACK_CHAT_URL = f"{FALLBACK_URL}/chat/completions"

FAST_RETRY = {
    "backoff_base_s": 0.01,
    "backoff_max_s": 0.02,
    "jitter_frac": 0.0,
}


class TinyResponse(BaseModel):
    status: str


def _role_cfg(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "provider": "local",
        "provider_type": "openai_compatible",
        "model": "test-model",
        "base_url": BASE_URL,
        "max_tokens": 256,
        "retry": dict(FAST_RETRY),
    }
    retry_overrides = overrides.pop("retry", None)
    cfg.update(overrides)
    if retry_overrides:
        cfg["retry"].update(retry_overrides)
    return cfg


def _make_client(recorder=None) -> tuple[ReliableLLMClient, dict[str, OpenAICompatAdapter]]:
    adapters: dict[str, OpenAICompatAdapter] = {}

    def adapter_for_config(cfg: dict[str, Any]) -> OpenAICompatAdapter:
        base_url = cfg["base_url"]
        if base_url not in adapters:
            adapters[base_url] = OpenAICompatAdapter(
                base_url=base_url,
                model=cfg["model"],
                default_max_tokens=cfg.get("max_tokens", 256),
            )
        return adapters[base_url]

    client = ReliableLLMClient(
        adapter_for_config=adapter_for_config,
        provider_config=lambda name: {},
        limiter=EndpointLimiter(),
        recorder=recorder,
    )
    return client, adapters


async def _close_all(adapters: dict[str, OpenAICompatAdapter]) -> None:
    for adapter in adapters.values():
        await adapter.close()


def _ok_json(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "model": "test-model",
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


@pytest.mark.asyncio
async def test_transport_retry_503_then_success(httpx_mock) -> None:
    httpx_mock.add_response(method="POST", url=CHAT_URL, status_code=503)
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok_json('{"status":"ok"}'))

    client, adapters = _make_client()
    result = await client.complete_structured(
        role="evaluation",
        role_cfg=_role_cfg(),
        fallback_cfg=None,
        messages=[{"role": "user", "content": "ping"}],
        response_model=TinyResponse,
    )
    await _close_all(adapters)

    assert result.parsed.status == "ok"
    assert result.response.attempts == 2


@pytest.mark.asyncio
async def test_transport_retry_exhaustion_raises(httpx_mock) -> None:
    for _ in range(3):
        httpx_mock.add_response(method="POST", url=CHAT_URL, status_code=503)

    client, adapters = _make_client()
    with pytest.raises(LLMRetriesExhausted):
        await client.complete_structured(
            role="evaluation",
            role_cfg=_role_cfg(),
            fallback_cfg=None,
            messages=[{"role": "user", "content": "ping"}],
            response_model=TinyResponse,
        )
    await _close_all(adapters)
    assert len(httpx_mock.get_requests()) == 3


@pytest.mark.asyncio
async def test_non_retryable_4xx_no_retry(httpx_mock) -> None:
    """401 must raise immediately as a non-retryable transport error.

    Note: a 4xx on a structured call first triggers the adapter's prompt-
    schema capability fallback (one extra request), then raises.
    """
    httpx_mock.add_response(method="POST", url=CHAT_URL, status_code=401)
    httpx_mock.add_response(method="POST", url=CHAT_URL, status_code=401)

    client, adapters = _make_client()
    with pytest.raises(LLMTransportError) as exc_info:
        await client.complete_structured(
            role="evaluation",
            role_cfg=_role_cfg(),
            fallback_cfg=None,
            messages=[{"role": "user", "content": "ping"}],
            response_model=TinyResponse,
        )
    await _close_all(adapters)
    assert not exc_info.value.retryable


@pytest.mark.asyncio
async def test_timeout_budget_is_separate_and_smaller(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), method="POST", url=CHAT_URL)
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), method="POST", url=CHAT_URL)

    client, adapters = _make_client()
    with pytest.raises(LLMRetriesExhausted):
        await client.complete_structured(
            role="evaluation",
            role_cfg=_role_cfg(),  # timeout_attempts default = 2
            fallback_cfg=None,
            messages=[{"role": "user", "content": "ping"}],
            response_model=TinyResponse,
        )
    await _close_all(adapters)
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_truncation_recall_grows_max_tokens(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST", url=CHAT_URL, json=_ok_json('{"status":"ok', finish_reason="length")
    )
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok_json('{"status":"ok"}'))

    client, adapters = _make_client()
    result = await client.complete_structured(
        role="evaluation",
        role_cfg=_role_cfg(),
        fallback_cfg=None,
        messages=[{"role": "user", "content": "ping"}],
        response_model=TinyResponse,
    )
    await _close_all(adapters)

    assert result.parsed.status == "ok"
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    first_body = json.loads(requests[0].read())
    second_body = json.loads(requests[1].read())
    assert first_body["max_tokens"] == 256
    assert second_body["max_tokens"] == 512  # doubled


@pytest.mark.asyncio
async def test_truncation_budget_exhausted_falls_back_to_brace_repair(httpx_mock) -> None:
    """Two length-truncated responses: re-call once, then brace-repair the second."""
    httpx_mock.add_response(
        method="POST", url=CHAT_URL, json=_ok_json('{"status":"ok', finish_reason="length")
    )
    httpx_mock.add_response(
        method="POST",
        url=CHAT_URL,
        json=_ok_json('{"status":"repaired"', finish_reason="length"),
    )

    client, adapters = _make_client()
    result = await client.complete_structured(
        role="evaluation",
        role_cfg=_role_cfg(),
        fallback_cfg=None,
        messages=[{"role": "user", "content": "ping"}],
        response_model=TinyResponse,
    )
    await _close_all(adapters)

    assert result.parsed.status == "repaired"
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_validation_feedback_retry_includes_bad_output_and_keeps_prefix(httpx_mock) -> None:
    original_messages = [
        {"role": "system", "content": "You extract statuses."},
        {"role": "user", "content": "ping"},
    ]
    httpx_mock.add_response(
        method="POST", url=CHAT_URL, json=_ok_json('{"wrong_field": true}')
    )
    httpx_mock.add_response(method="POST", url=CHAT_URL, json=_ok_json('{"status":"ok"}'))

    client, adapters = _make_client()
    result = await client.complete_structured(
        role="evaluation",
        role_cfg=_role_cfg(),
        fallback_cfg=None,
        messages=original_messages,
        response_model=TinyResponse,
    )
    await _close_all(adapters)

    assert result.parsed.status == "ok"
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    retry_messages = json.loads(requests[1].read())["messages"]
    # Original messages are a byte-identical prefix (prefix-cache friendly).
    assert retry_messages[: len(original_messages)] == original_messages
    # Bad output echoed back as an assistant turn, then the feedback.
    assert retry_messages[len(original_messages)]["role"] == "assistant"
    assert "wrong_field" in retry_messages[len(original_messages)]["content"]
    feedback = retry_messages[len(original_messages) + 1]
    assert feedback["role"] == "user"
    assert "failed validation" in feedback["content"]
    assert "TinyResponse" in feedback["content"]


@pytest.mark.asyncio
async def test_validation_exhaustion_raises_retries_exhausted(httpx_mock) -> None:
    for _ in range(3):  # first + validation_attempts(2)
        httpx_mock.add_response(
            method="POST", url=CHAT_URL, json=_ok_json('{"wrong_field": true}')
        )

    client, adapters = _make_client()
    with pytest.raises(LLMRetriesExhausted):
        await client.complete_structured(
            role="evaluation",
            role_cfg=_role_cfg(),
            fallback_cfg=None,
            messages=[{"role": "user", "content": "ping"}],
            response_model=TinyResponse,
        )
    await _close_all(adapters)
    assert len(httpx_mock.get_requests()) == 3


@pytest.mark.asyncio
async def test_fallback_chain_used_after_primary_exhaustion(httpx_mock) -> None:
    for _ in range(3):
        httpx_mock.add_response(method="POST", url=CHAT_URL, status_code=503)
    httpx_mock.add_response(
        method="POST", url=FALLBACK_CHAT_URL, json=_ok_json('{"status":"fallback"}')
    )

    records: list[LLMCallRecord] = []

    async def recorder(record: LLMCallRecord) -> None:
        records.append(record)

    client, adapters = _make_client(recorder)
    result = await client.complete_structured(
        role="evaluation",
        role_cfg=_role_cfg(),
        fallback_cfg=_role_cfg(base_url=FALLBACK_URL, model="big-model"),
        messages=[{"role": "user", "content": "ping"}],
        response_model=TinyResponse,
    )
    await _close_all(adapters)

    assert result.parsed.status == "fallback"
    assert len(records) == 1
    assert records[0].fallback_used is True
    assert records[0].model == "big-model"
    assert records[0].outcome == "success"


@pytest.mark.asyncio
async def test_no_fallback_config_means_no_fallback(httpx_mock) -> None:
    for _ in range(3):
        httpx_mock.add_response(method="POST", url=CHAT_URL, status_code=503)

    client, adapters = _make_client()
    with pytest.raises(LLMRetriesExhausted):
        await client.complete_structured(
            role="evaluation",
            role_cfg=_role_cfg(),
            fallback_cfg=None,
            messages=[{"role": "user", "content": "ping"}],
            response_model=TinyResponse,
        )
    await _close_all(adapters)
    assert len(httpx_mock.get_requests()) == 3  # primary only


@pytest.mark.asyncio
async def test_pre_set_cancel_token_prevents_any_request(httpx_mock) -> None:
    token = CancelToken()
    token.cancel(CancelReason.user_cancel)
    ctx = set_job_context(JobContext(cancel_token=token))
    try:
        client, adapters = _make_client()
        with pytest.raises(OperationCancelled):
            await client.complete_structured(
                role="evaluation",
                role_cfg=_role_cfg(),
                fallback_cfg=None,
                messages=[{"role": "user", "content": "ping"}],
                response_model=TinyResponse,
            )
        await _close_all(adapters)
    finally:
        from libs.core.run_context import current_job_context

        current_job_context.reset(ctx)
    assert len(httpx_mock.get_requests()) == 0


@pytest.mark.asyncio
async def test_cancel_mid_flight_interrupts_call(httpx_mock) -> None:
    async def slow_response(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return httpx.Response(200, json=_ok_json('{"status":"ok"}'))

    httpx_mock.add_callback(slow_response, method="POST", url=CHAT_URL)

    token = CancelToken()
    ctx = set_job_context(JobContext(cancel_token=token))

    def trip_soon() -> None:
        time.sleep(0.2)
        token.cancel(CancelReason.user_cancel)

    thread = threading.Thread(target=trip_soon)
    thread.start()
    try:
        client, adapters = _make_client()
        start = time.monotonic()
        with pytest.raises(OperationCancelled):
            await client.complete_structured(
                role="evaluation",
                role_cfg=_role_cfg(),
                fallback_cfg=None,
                messages=[{"role": "user", "content": "ping"}],
                response_model=TinyResponse,
            )
        elapsed = time.monotonic() - start
        await _close_all(adapters)
    finally:
        thread.join()
        from libs.core.run_context import current_job_context

        current_job_context.reset(ctx)

    assert elapsed < 5.0  # interrupted well before the 10s response


@pytest.mark.asyncio
async def test_plain_complete_truncation_recall(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST", url=CHAT_URL, json=_ok_json("partial text", finish_reason="length")
    )
    httpx_mock.add_response(
        method="POST", url=CHAT_URL, json=_ok_json("full text", finish_reason="stop")
    )

    client, adapters = _make_client()
    response = await client.complete(
        role="summarization",
        role_cfg=_role_cfg(),
        fallback_cfg=None,
        messages=[{"role": "user", "content": "summarize"}],
    )
    await _close_all(adapters)

    assert response.content == "full text"
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_recorder_receives_failure_record(httpx_mock) -> None:
    for _ in range(3):
        httpx_mock.add_response(method="POST", url=CHAT_URL, status_code=503)

    records: list[LLMCallRecord] = []

    async def recorder(record: LLMCallRecord) -> None:
        records.append(record)

    client, adapters = _make_client(recorder)
    with pytest.raises(LLMRetriesExhausted):
        await client.complete_structured(
            role="evaluation",
            role_cfg=_role_cfg(),
            fallback_cfg=None,
            messages=[{"role": "user", "content": "ping"}],
            response_model=TinyResponse,
        )
    await _close_all(adapters)

    assert len(records) == 1
    assert records[0].outcome == "transport_error"
    assert records[0].attempts == 3
    assert len(records[0].attempt_log) == 3


def test_retry_policy_from_role_config_merges_overrides() -> None:
    policy = RetryPolicy.from_role_config({"retry": {"validation_attempts": 5}})
    assert policy.validation_attempts == 5
    assert policy.transport_attempts == 3  # default preserved

    reduced = policy.reduced_for_fallback()
    assert reduced.transport_attempts == 2
    assert reduced.validation_attempts == 1
