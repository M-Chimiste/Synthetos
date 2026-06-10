"""OpenAI hosted LLM adapter using the openai SDK."""

from __future__ import annotations

import os
import time
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from libs.adapters.llm.errors import (
    LLMTruncationError,
    LLMValidationError,
    normalize_finish_reason,
)
from libs.adapters.llm.json_repair import validate_with_light_repair
from libs.core.logging import get_logger
from libs.schemas.model_gateway import CompletionResponse, StructuredCompletion

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class OpenAIAdapter:
    """LLM adapter for the OpenAI hosted API.

    Uses the official ``openai`` SDK. Structured output uses
    ``response_format`` with ``json_schema`` type.

    SDK retries are disabled (``max_retries=0``): the reliability layer owns
    retry policy, and stacked retries would multiply.
    """

    provider_name: str = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        default_temperature: float = 0.7,
        default_max_tokens: int = 4096,
        timeout_s: float = 600.0,
        sampling: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.sampling = dict(sampling or {})

        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY or pass api_key.")

        self._client = openai.AsyncOpenAI(
            api_key=resolved_key,
            timeout=timeout_s,
            max_retries=0,
        )

    def _sampling_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        for key in ("top_p", "seed", "stop"):
            if key in self.sampling:
                kwargs[key] = self.sampling[key]
        return kwargs

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Send a chat completion via the OpenAI API."""
        log.debug("openai.complete", model=self.model)

        start = time.monotonic()
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature if temperature is not None else self.default_temperature,
                max_tokens=max_tokens if max_tokens is not None else self.default_max_tokens,
                **self._sampling_kwargs(),
            )
        except openai.APIError as exc:
            log.error("openai.api_error", error=str(exc))
            raise
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = resp.choices[0]
        content = choice.message.content or ""
        usage = resp.usage

        return CompletionResponse(
            content=content,
            model=resp.model,
            provider=self.provider_name,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            finish_reason=normalize_finish_reason(choice.finish_reason),
            latency_ms=latency_ms,
        )

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> StructuredCompletion[T]:
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

        start = time.monotonic()
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
                **self._sampling_kwargs(),
            )
        except openai.APIError as exc:
            log.error("openai.structured_api_error", error=str(exc))
            raise
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = resp.choices[0]
        content = choice.message.content or ""
        usage = resp.usage
        finish_reason = normalize_finish_reason(choice.finish_reason)

        response = CompletionResponse(
            content=content,
            model=resp.model,
            provider=self.provider_name,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
        )

        try:
            parsed = validate_with_light_repair(response_model, content)
        except ValidationError as exc:
            if finish_reason == "length":
                raise LLMTruncationError(
                    f"{response_model.__name__} generation hit max_tokens",
                    raw_content=content,
                    response=response,
                ) from exc
            raise LLMValidationError(
                f"{response_model.__name__} validation failed",
                raw_content=content,
                validation_detail=str(exc),
                response=response,
            ) from exc

        return StructuredCompletion(parsed=parsed, response=response)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
