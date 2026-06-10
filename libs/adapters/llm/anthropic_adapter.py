"""Anthropic LLM adapter using the anthropic SDK."""

from __future__ import annotations

import json
import os
import time
from typing import Any, TypeVar

import anthropic
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


class AnthropicAdapter:
    """LLM adapter for the Anthropic Messages API.

    Uses the official ``anthropic`` SDK. Structured output is achieved
    via tool-use: a single tool whose ``input_schema`` matches the
    target Pydantic model is supplied, and the model is forced to call it.

    SDK retries are disabled (``max_retries=0``): the reliability layer owns
    retry policy, and stacked retries would multiply.
    """

    provider_name: str = "anthropic"

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

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Anthropic API key is required. Set ANTHROPIC_API_KEY or pass api_key."
            )

        self._client = anthropic.AsyncAnthropic(
            api_key=resolved_key,
            timeout=timeout_s,
            max_retries=0,
        )

    def _apply_sampling(self, kwargs: dict[str, Any]) -> None:
        if "top_p" in self.sampling:
            kwargs["top_p"] = self.sampling["top_p"]
        if "stop" in self.sampling:
            stop = self.sampling["stop"]
            kwargs["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)
        if "seed" in self.sampling:
            log.debug("anthropic.seed_unsupported", model=self.model)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Send a chat completion via the Anthropic Messages API."""
        system_text, api_messages = _split_system(messages)

        kwargs: dict = {
            "model": self.model,
            "messages": api_messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
        }
        if system_text:
            kwargs["system"] = system_text
        self._apply_sampling(kwargs)

        log.debug("anthropic.complete", model=self.model)

        start = time.monotonic()
        try:
            resp = await self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            log.error("anthropic.api_error", error=str(exc))
            raise
        latency_ms = int((time.monotonic() - start) * 1000)

        content = _extract_text(resp)

        return CompletionResponse(
            content=content,
            model=resp.model,
            provider=self.provider_name,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            finish_reason=normalize_finish_reason(resp.stop_reason),
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
        """Generate structured output using Anthropic tool-use.

        A single tool whose input_schema matches the Pydantic model is
        supplied with ``tool_choice`` forced so the model must call it.
        The tool_use block's input is then validated into the model.
        """
        if not issubclass(response_model, BaseModel):
            msg = f"response_model must be a Pydantic BaseModel subclass, got {response_model}"
            raise TypeError(msg)

        schema = response_model.model_json_schema()
        tool_name = f"structured_{response_model.__name__}"

        tool_def = {
            "name": tool_name,
            "description": f"Return structured data as {response_model.__name__}.",
            "input_schema": schema,
        }

        system_text, api_messages = _split_system(messages)

        kwargs: dict = {
            "model": self.model,
            "messages": api_messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "tools": [tool_def],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        if system_text:
            kwargs["system"] = system_text
        self._apply_sampling(kwargs)

        log.debug(
            "anthropic.complete_structured",
            model=self.model,
            response_model=response_model.__name__,
        )

        start = time.monotonic()
        try:
            resp = await self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            log.error("anthropic.structured_api_error", error=str(exc))
            raise
        latency_ms = int((time.monotonic() - start) * 1000)

        finish_reason = normalize_finish_reason(resp.stop_reason)
        text = _extract_text(resp)

        # Find the tool_use content block
        raw_content = text
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool_name:
                raw_input = block.input
                raw_content = (
                    raw_input if isinstance(raw_input, str) else json.dumps(raw_input)
                )
                break

        response = CompletionResponse(
            content=raw_content,
            model=resp.model,
            provider=self.provider_name,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
        )

        try:
            parsed = validate_with_light_repair(response_model, raw_content)
        except ValidationError as exc:
            if finish_reason == "length":
                raise LLMTruncationError(
                    f"{response_model.__name__} generation hit max_tokens",
                    raw_content=raw_content,
                    response=response,
                ) from exc
            raise LLMValidationError(
                f"{response_model.__name__} validation failed",
                raw_content=raw_content,
                validation_detail=str(exc),
                response=response,
            ) from exc

        return StructuredCompletion(parsed=parsed, response=response)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()


def _split_system(
    messages: list[dict[str, str]],
) -> tuple[str | None, list[dict[str, str]]]:
    """Separate a leading system message from the rest.

    Anthropic's API takes ``system`` as a top-level parameter rather than
    as a message role, so we extract it here.
    """
    if messages and messages[0].get("role") == "system":
        return messages[0]["content"], messages[1:]
    return None, list(messages)


def _extract_text(resp: anthropic.types.Message) -> str:
    """Extract text content from an Anthropic Message response."""
    parts: list[str] = []
    for block in resp.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts) if parts else ""
