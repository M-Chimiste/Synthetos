from __future__ import annotations

import pytest
from pydantic import BaseModel

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
                {"message": {"content": "<think>\n\n</think>\n\nsynthetos-ready"}}
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


@pytest.mark.asyncio
async def test_openai_compat_structured_strips_reasoning_before_parse(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [
                {"message": {"content": '<think>\n\n</think>\n\n{"status":"ok"}'}}
            ],
        },
    )
    adapter = OpenAICompatAdapter(
        base_url="http://local.test/v1",
        model="local-model",
        strip_reasoning_tags=True,
    )

    response = await adapter.complete_structured(
        [{"role": "user", "content": "ping"}],
        TinyResponse,
    )
    await adapter.close()

    assert response.status == "ok"


@pytest.mark.asyncio
async def test_openai_compat_structured_uses_mnemosyne_json_schema_shape(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [{"message": {"content": '{"status":"ok"}'}}],
        },
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    response = await adapter.complete_structured(
        [{"role": "user", "content": "ping"}],
        TinyResponse,
    )
    await adapter.close()

    request = httpx_mock.get_request()
    assert request is not None
    body = request.read().decode()
    assert '"response_format":{"type":"json_schema","schema":' in body
    assert '"json_schema":' not in body
    assert response.status == "ok"


@pytest.mark.asyncio
async def test_openai_compat_structured_fallback_repairs_truncated_json(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [{"message": {"content": '{"description":"schema echo"}'}}],
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [{"message": {"content": '{"status":"ok"'}}],
        },
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    response = await adapter.complete_structured(
        [{"role": "user", "content": "ping"}],
        TinyResponse,
    )
    await adapter.close()

    assert response.status == "ok"


@pytest.mark.asyncio
async def test_openai_compat_structured_repairs_invalid_json_backslashes(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://local.test/v1/chat/completions",
        json={
            "model": "local-model",
            "choices": [{"message": {"content": '{"status":"uses \\mathbf{x}"}'}}],
        },
    )
    adapter = OpenAICompatAdapter(base_url="http://local.test/v1", model="local-model")

    response = await adapter.complete_structured(
        [{"role": "user", "content": "ping"}],
        TinyResponse,
    )
    await adapter.close()

    assert response.status == r"uses \mathbf{x}"
