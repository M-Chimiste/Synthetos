"""OpenAI-compatible LLM adapter for local providers (LMStudio, Ollama, VLLM)."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from libs.core.logging import get_logger
from libs.schemas.model_gateway import CompletionResponse

log = get_logger(__name__)
T = TypeVar("T")


class OpenAICompatAdapter:
    """LLM adapter for any OpenAI-compatible API endpoint.

    Works with LMStudio, Ollama, VLLM, and similar local servers that
    expose an OpenAI-compatible ``/v1/chat/completions`` endpoint.
    Uses httpx directly -- no vendor SDK required.
    """

    provider_name: str = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "not-needed",
        default_temperature: float = 0.7,
        default_max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Send a chat completion request."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
        }

        log.debug("openai_compat.complete", model=self.model, base_url=self.base_url)

        try:
            resp = await self._client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.error(
                "openai_compat.http_error",
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            raise
        except httpx.RequestError as exc:
            log.error("openai_compat.request_error", error=str(exc))
            raise

        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})

        return CompletionResponse(
            content=choice["message"]["content"],
            model=data.get("model", self.model),
            provider=self.provider_name,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        """Generate a structured completion.

        Attempts to use ``response_format`` with ``json_schema`` type first.
        If that fails (e.g. the endpoint doesn't support it), falls back to
        requesting JSON output and parsing it from the response content.
        """
        if not issubclass(response_model, BaseModel):
            msg = f"response_model must be a Pydantic BaseModel subclass, got {response_model}"
            raise TypeError(msg)

        schema = response_model.model_json_schema()

        # Try native json_schema response_format first
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": response_model.__name__, "schema": schema},
            },
        }

        log.debug(
            "openai_compat.complete_structured",
            model=self.model,
            response_model=response_model.__name__,
        )

        try:
            resp = await self._client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return response_model.model_validate_json(content)
        except httpx.HTTPStatusError:
            log.info(
                "openai_compat.json_schema_unsupported, falling back to JSON parsing",
                model=self.model,
            )
        except (json.JSONDecodeError, Exception) as exc:
            log.info(
                "openai_compat.json_schema_parse_failed, falling back",
                error=str(exc),
            )

        # Fallback: ask for JSON output in the system prompt
        augmented = list(messages)
        json_instruction = (
            f"Respond ONLY with valid JSON matching this schema: {json.dumps(schema)}"
        )
        if augmented and augmented[0]["role"] == "system":
            augmented[0] = {
                "role": "system",
                "content": augmented[0]["content"] + "\n\n" + json_instruction,
            }
        else:
            augmented.insert(0, {"role": "system", "content": json_instruction})

        fallback_payload: dict[str, Any] = {
            "model": self.model,
            "messages": augmented,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
        }

        try:
            resp = await self._client.post("/v1/chat/completions", json=fallback_payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.error(
                "openai_compat.fallback_http_error",
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            raise
        except httpx.RequestError as exc:
            log.error("openai_compat.fallback_request_error", error=str(exc))
            raise

        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Strip markdown code fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [ln for ln in lines[1:] if ln.strip() != "```"]
            cleaned = "\n".join(lines)

        return response_model.model_validate_json(cleaned)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
