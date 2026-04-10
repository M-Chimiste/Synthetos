"""OpenAI hosted LLM adapter using the openai SDK."""

from __future__ import annotations

import os
from typing import TypeVar

import openai
from pydantic import BaseModel

from libs.core.logging import get_logger
from libs.schemas.model_gateway import CompletionResponse

log = get_logger(__name__)
T = TypeVar("T")


class OpenAIAdapter:
    """LLM adapter for the OpenAI hosted API.

    Uses the official ``openai`` SDK. Structured output uses
    ``response_format`` with ``json_schema`` type.
    """

    provider_name: str = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        default_temperature: float = 0.7,
        default_max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY or pass api_key.")

        self._client = openai.AsyncOpenAI(api_key=resolved_key)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Send a chat completion via the OpenAI API."""
        log.debug("openai.complete", model=self.model)

        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature if temperature is not None else self.default_temperature,
                max_tokens=max_tokens if max_tokens is not None else self.default_max_tokens,
            )
        except openai.APIError as exc:
            log.error("openai.api_error", error=str(exc))
            raise

        choice = resp.choices[0]
        content = choice.message.content or ""
        usage = resp.usage

        return CompletionResponse(
            content=content,
            model=resp.model,
            provider=self.provider_name,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        """Generate structured output using ``response_format`` with ``json_schema``."""
        if not issubclass(response_model, BaseModel):
            msg = f"response_model must be a Pydantic BaseModel subclass, got {response_model}"
            raise TypeError(msg)

        schema = response_model.model_json_schema()

        log.debug(
            "openai.complete_structured",
            model=self.model,
            response_model=response_model.__name__,
        )

        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature if temperature is not None else self.default_temperature,
                max_tokens=max_tokens if max_tokens is not None else self.default_max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
        except openai.APIError as exc:
            log.error("openai.structured_api_error", error=str(exc))
            raise

        content = resp.choices[0].message.content or ""
        return response_model.model_validate_json(content)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
