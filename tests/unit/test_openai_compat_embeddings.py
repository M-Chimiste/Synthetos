"""Tests for OpenAI-compatible embedding transport handling."""

from __future__ import annotations

import httpx
import pytest

from libs.adapters.embeddings.openai_compat import OpenAICompatEmbeddingAdapter
from libs.core.errors import RetryableOperatorError


class _FailingClient:
    async def post(self, *_args, **_kwargs):
        request = httpx.Request("POST", "http://embeddings.local/v1/embeddings")
        raise httpx.ConnectError("All connection attempts failed", request=request)


class _HTTPStatusClient:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    async def post(self, *_args, **_kwargs):
        request = httpx.Request("POST", "http://embeddings.local/v1/embeddings")
        response = httpx.Response(self.status_code, request=request, text="busy")
        return response


@pytest.mark.asyncio
async def test_embedding_transport_failure_is_retryable() -> None:
    adapter = OpenAICompatEmbeddingAdapter(
        base_url="http://embeddings.local/v1",
        model="test-embeddings",
    )
    adapter._client = _FailingClient()  # type: ignore[assignment]

    with pytest.raises(RetryableOperatorError, match="embedding endpoint request failed"):
        await adapter.embed(["hello"])


@pytest.mark.asyncio
async def test_embedding_5xx_failure_is_retryable() -> None:
    adapter = OpenAICompatEmbeddingAdapter(
        base_url="http://embeddings.local/v1",
        model="test-embeddings",
    )
    adapter._client = _HTTPStatusClient(503)  # type: ignore[assignment]

    with pytest.raises(RetryableOperatorError, match="embedding endpoint HTTP 503"):
        await adapter.embed(["hello"])


@pytest.mark.asyncio
async def test_embedding_4xx_failure_stays_non_retryable() -> None:
    adapter = OpenAICompatEmbeddingAdapter(
        base_url="http://embeddings.local/v1",
        model="test-embeddings",
    )
    adapter._client = _HTTPStatusClient(400)  # type: ignore[assignment]

    with pytest.raises(httpx.HTTPStatusError):
        await adapter.embed(["hello"])
