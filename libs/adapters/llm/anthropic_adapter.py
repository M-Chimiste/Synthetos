"""Anthropic LLM adapter using the anthropic SDK."""

from __future__ import annotations

import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from libs.core.logging import get_logger
from libs.schemas.model_gateway import CompletionResponse

log = get_logger(__name__)
T = TypeVar("T")


class AnthropicAdapter:
    """LLM adapter for the Anthropic Messages API.

    Uses the official ``anthropic`` SDK. Structured output is achieved
    via tool-use: a single tool whose ``input_schema`` matches the
    target Pydantic model is supplied, and the model is forced to call it.
    """

    provider_name: str = "anthropic"

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

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Anthropic API key is required. Set ANTHROPIC_API_KEY or pass api_key."
            )

        self._client = anthropic.AsyncAnthropic(api_key=resolved_key)

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

        log.debug("anthropic.complete", model=self.model)

        try:
            resp = await self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            log.error("anthropic.api_error", error=str(exc))
            raise

        content = _extract_text(resp)

        return CompletionResponse(
            content=content,
            model=resp.model,
            provider=self.provider_name,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
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

        log.debug(
            "anthropic.complete_structured",
            model=self.model,
            response_model=response_model.__name__,
        )

        try:
            resp = await self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            log.error("anthropic.structured_api_error", error=str(exc))
            raise

        # Find the tool_use content block
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool_name:
                raw_input = block.input
                if isinstance(raw_input, str):
                    return response_model.model_validate_json(raw_input)
                return response_model.model_validate(raw_input)

        # Fallback: try parsing text content as JSON
        text = _extract_text(resp)
        log.warning("anthropic.no_tool_use_block, attempting JSON parse from text")
        return response_model.model_validate_json(text)

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
