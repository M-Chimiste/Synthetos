"""OpenAI-compatible embedding adapter using httpx."""

from __future__ import annotations

from typing import Any

import httpx

from libs.core.logging import get_logger

log = get_logger(__name__)


class OpenAICompatEmbeddingAdapter:
    """Embedding adapter for any OpenAI-compatible ``/v1/embeddings`` endpoint.

    Works with LMStudio, Ollama, VLLM, and similar local servers.
    Uses httpx directly -- no vendor SDK required.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dimensions: int = 768,
        api_key: str = "not-needed",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Compute embeddings for a list of texts in a single request."""
        if not texts:
            return []

        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
        }
        # Include dimensions if the endpoint supports it
        if self.dimensions:
            payload["dimensions"] = self.dimensions

        log.debug(
            "embedding.embed",
            model=self.model,
            num_texts=len(texts),
        )

        try:
            resp = await self._client.post("/v1/embeddings", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.error(
                "embedding.http_error",
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            raise
        except httpx.RequestError as exc:
            log.error("embedding.request_error", error=str(exc))
            raise

        data = resp.json()
        # Sort by index to ensure correct ordering
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    async def embed_batch(self, texts: list[str], *, batch_size: int = 64) -> list[list[float]]:
        """Compute embeddings in batches to handle large input lists.

        Splits ``texts`` into chunks of ``batch_size`` and calls ``embed``
        for each chunk, concatenating the results.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            log.debug(
                "embedding.embed_batch",
                batch_start=i,
                batch_size=len(batch),
                total=len(texts),
            )
            embeddings = await self.embed(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
