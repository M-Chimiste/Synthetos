"""Google Gemini LLM adapter using the google-genai SDK."""

from __future__ import annotations

import os
from typing import Any, TypeVar, cast

from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel

from libs.core.logging import get_logger
from libs.schemas.model_gateway import CompletionResponse

log = get_logger(__name__)
T = TypeVar("T")


class GoogleAdapter:
    """LLM adapter for Google Gemini via the ``google-genai`` SDK.

    Structured output uses ``generation_config`` with ``response_schema``.
    """

    provider_name: str = "google"

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

        resolved_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not resolved_key:
            raise ValueError("Google API key is required. Set GOOGLE_API_KEY or pass api_key.")

        self._client = genai.Client(api_key=resolved_key)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Send a completion request to Gemini."""
        system_text, contents = _build_contents(messages)

        config = genai_types.GenerateContentConfig(
            temperature=temperature if temperature is not None else self.default_temperature,
            max_output_tokens=max_tokens if max_tokens is not None else self.default_max_tokens,
        )
        if system_text:
            config.system_instruction = system_text

        log.debug("google.complete", model=self.model)

        try:
            resp = await self._client.aio.models.generate_content(
                model=self.model,
                contents=cast(list[Any], contents),
                config=config,
            )
        except Exception as exc:
            log.error("google.api_error", error=str(exc))
            raise

        text = resp.text or ""
        input_tokens = None
        output_tokens = None
        if resp.usage_metadata:
            input_tokens = resp.usage_metadata.prompt_token_count
            output_tokens = resp.usage_metadata.candidates_token_count

        return CompletionResponse(
            content=text,
            model=self.model,
            provider=self.provider_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        """Generate structured output using ``response_schema`` in generation config."""
        if not issubclass(response_model, BaseModel):
            msg = f"response_model must be a Pydantic BaseModel subclass, got {response_model}"
            raise TypeError(msg)

        system_text, contents = _build_contents(messages)

        config = genai_types.GenerateContentConfig(
            temperature=temperature if temperature is not None else self.default_temperature,
            max_output_tokens=max_tokens if max_tokens is not None else self.default_max_tokens,
            response_mime_type="application/json",
            response_schema=response_model,
        )
        if system_text:
            config.system_instruction = system_text

        log.debug(
            "google.complete_structured",
            model=self.model,
            response_model=response_model.__name__,
        )

        try:
            resp = await self._client.aio.models.generate_content(
                model=self.model,
                contents=cast(list[Any], contents),
                config=config,
            )
        except Exception as exc:
            log.error("google.structured_api_error", error=str(exc))
            raise

        text = resp.text or ""
        return response_model.model_validate_json(text)

    async def close(self) -> None:
        """Close resources (no-op for google-genai client)."""
        pass


def _build_contents(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[genai_types.Content]]:
    """Convert OpenAI-style messages to Gemini content format.

    Returns the system instruction (if any) and a list of Content objects.
    """
    system_text: str | None = None
    contents: list[genai_types.Content] = []

    for msg in messages:
        role = msg["role"]
        text = msg["content"]

        if role == "system":
            system_text = text
            continue

        # Gemini uses "user" and "model" roles
        gemini_role = "model" if role == "assistant" else "user"
        contents.append(
            genai_types.Content(
                role=gemini_role,
                parts=[genai_types.Part(text=text)],
            )
        )

    return system_text, contents
