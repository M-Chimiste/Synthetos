from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from libs.adapters.llm.errors import LLMTruncationError, LLMValidationError
from libs.adapters.llm.openai_compat import OpenAICompatAdapter


class TinyResponse(BaseModel):
    status: str


@pytest.mark.asyncio
async def test_openai_compat_passes_extra_body_and_strips_reasoning(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [
                {
                    "message": {"content": "<think>\n\n</think>\n\nsynthetos-ready"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        },
    )
    adapter = OpenAICompatAdapter(
        base_url="http://local.test/v1",
        model="local-model",
        extra_body={"reasoning_format": "none"},
        strip_reasoning_tags=True,
    )

    response = await adapter.complete([{"role": "user", "content": "ping"}])
    await adapter.close()

    request = httpx_mock.get_request()
    assert request is not None
    assert request.read().decode().find('"reasoning_format":"none"') != -1
    assert response.content == "synthetos-ready"
    assert response.finish_reason == "stop"
    assert response.latency_ms is not None


@pytest.mark.asyncio
async def test_openai_compat_passes_sampling_params(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        },
    )
    adapter = OpenAICompatAdapter(
        base_url="http://local.test/v1",
        model="local-model",
        sampling={"top_p": 0.9, "seed": 42},
    )

    await adapter.complete([{"role": "user", "content": "ping"}])
    await adapter.close()

    request = httpx_mock.get_request()
    assert request is not None
    body = request.read().decode()
    assert '"top_p":0.9' in body
    assert '"seed":42' in body


@pytest.mark.asyncio
async def test_openai_compat_structured_strips_reasoning_before_parse(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [
                {
                    "message": {"content": '<think>\n\n</think>\n\n{"status":"ok"}'},
                    "finish_reason": "stop",
                }
            ],
        },
    )
    adapter = OpenAICompatAdapter(
        base_url="http://local.test/v1",
        model="local-model",
        strip_reasoning_tags=True,
    )

    result = await adapter.complete_structured(
        [{"role": "user", "content": "ping"}],
        TinyResponse,
    )
    await adapter.close()

    assert result.parsed.status == "ok"
    assert result.response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_openai_compat_structured_sends_dual_json_schema_shape(httpx_mock) -> None:
    """Payload carries both llama.cpp ("schema") and vLLM ("json_schema") keys."""
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [{"message": {"content": '{"status":"ok"}'}, "finish_reason": "stop"}],
        },
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    result = await adapter.complete_structured(
        [{"role": "user", "content": "ping"}],
        TinyResponse,
    )
    await adapter.close()

    request = httpx_mock.get_request()
    assert request is not None
    body = request.read().decode()
    assert '"response_format":{"type":"json_schema","schema":' in body
    assert '"json_schema":{"name":"TinyResponse"' in body
    assert result.parsed.status == "ok"


@pytest.mark.asyncio
async def test_openai_compat_4xx_falls_back_to_prompt_schema(httpx_mock) -> None:
    """A server rejecting response_format (400) gets one prompt-schema retry."""
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        status_code=400,
    )
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [{"message": {"content": '{"status":"ok"}'}, "finish_reason": "stop"}],
        },
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    result = await adapter.complete_structured(
        [{"role": "user", "content": "ping"}],
        TinyResponse,
    )
    await adapter.close()

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    fallback_body = requests[1].read().decode()
    assert "response_format" not in fallback_body
    assert "Respond ONLY with one valid JSON object" in fallback_body
    assert result.parsed.status == "ok"


@pytest.mark.asyncio
async def test_openai_compat_5xx_does_not_trigger_prompt_fallback(httpx_mock) -> None:
    """5xx is a transport problem for the reliability layer, not a capability gap."""
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        status_code=503,
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    with pytest.raises(httpx.HTTPStatusError):
        await adapter.complete_structured(
            [{"role": "user", "content": "ping"}],
            TinyResponse,
        )
    await adapter.close()

    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.asyncio
async def test_openai_compat_truncated_output_raises_truncation_error(httpx_mock) -> None:
    """finish_reason == length with unparseable JSON surfaces as LLMTruncationError."""
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [{"message": {"content": '{"status":"ok"'}, "finish_reason": "length"}],
        },
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    with pytest.raises(LLMTruncationError) as exc_info:
        await adapter.complete_structured(
            [{"role": "user", "content": "ping"}],
            TinyResponse,
        )
    await adapter.close()

    assert exc_info.value.raw_content == '{"status":"ok"'
    assert exc_info.value.response.finish_reason == "length"


@pytest.mark.asyncio
async def test_openai_compat_invalid_output_raises_validation_error(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [
                {"message": {"content": '{"wrong_field": 1}'}, "finish_reason": "stop"}
            ],
        },
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    with pytest.raises(LLMValidationError) as exc_info:
        await adapter.complete_structured(
            [{"role": "user", "content": "ping"}],
            TinyResponse,
        )
    await adapter.close()

    assert "status" in exc_info.value.validation_detail
    assert exc_info.value.raw_content == '{"wrong_field": 1}'


@pytest.mark.asyncio
async def test_openai_compat_structured_repairs_invalid_json_backslashes(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [
                {
                    "message": {"content": '{"status":"uses \\mathbf{x}"}'},
                    "finish_reason": "stop",
                }
            ],
        },
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    result = await adapter.complete_structured(
        [{"role": "user", "content": "ping"}],
        TinyResponse,
    )
    await adapter.close()

    assert result.parsed.status == r"uses \mathbf{x}"
