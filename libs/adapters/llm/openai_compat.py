"""OpenAI-compatible LLM adapter for local providers (LMStudio, Ollama, VLLM)."""

from __future__ import annotations

import json
import time
from typing import Any, TypeVar

import httpx
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


class OpenAICompatAdapter:
    """LLM adapter for any OpenAI-compatible API endpoint.

    Works with LMStudio, Ollama, VLLM, and similar local servers that
    expose an OpenAI-compatible ``/v1/chat/completions`` endpoint.
    Uses httpx directly -- no vendor SDK required.

    The adapter stays dumb: one provider request per call, light JSON repair
    only, and typed errors (truncation/validation) for the reliability layer
    to act on. The single exception is the json_schema capability fallback:
    if the server rejects ``response_format`` with a 4xx, the request is
    re-sent once with the schema injected into the system prompt.
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
        extra_body: dict[str, Any] | None = None,
        strip_reasoning_tags: bool = False,
        timeout_s: float = 600.0,
        sampling: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_completions_path = (
            "/chat/completions" if self.base_url.endswith("/v1") else "/v1/chat/completions"
        )
        self.model = model
        self.api_key = api_key
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.extra_body = dict(extra_body or {})
        self.strip_reasoning_tags = strip_reasoning_tags
        self.sampling = dict(sampling or {})
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_s, connect=10.0),
        )

    def _base_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
        }
        payload.update(self.sampling)
        payload.update(self.extra_body)
        return payload

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._client.post(self.chat_completions_path, json=payload)
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
        return resp.json()

    def _to_response(self, data: dict[str, Any], latency_ms: int) -> CompletionResponse:
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        content = self._clean_content(choice["message"]["content"] or "")
        return CompletionResponse(
            content=content,
            model=data.get("model", self.model),
            provider=self.provider_name,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            finish_reason=normalize_finish_reason(choice.get("finish_reason")),
            latency_ms=latency_ms,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Send a chat completion request."""
        payload = self._base_payload(messages, temperature, max_tokens)
        log.debug("openai_compat.complete", model=self.model, base_url=self.base_url)
        start = time.monotonic()
        data = await self._post(payload)
        return self._to_response(data, int((time.monotonic() - start) * 1000))

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> StructuredCompletion[T]:
        """Generate a structured completion.

        Attempts ``response_format`` with ``json_schema`` first. If the
        server rejects the request shape (4xx), falls back once to prompt-
        injected schema. Parse failures raise :class:`LLMTruncationError`
        (when generation hit max_tokens) or :class:`LLMValidationError` for
        the reliability layer to handle -- the adapter never re-prompts on
        validation failure.
        """
        if not issubclass(response_model, BaseModel):
            msg = f"response_model must be a Pydantic BaseModel subclass, got {response_model}"
            raise TypeError(msg)

        schema = response_model.model_json_schema()
        response_format = {
            "type": "json_schema",
            # llama.cpp accepts the schema here.
            "schema": schema,
            # vLLM expects the OpenAI-compatible json_schema wrapper.
            "json_schema": {
                "name": response_model.__name__,
                "schema": schema,
            },
        }

        payload = self._base_payload(messages, temperature, max_tokens)
        payload["response_format"] = response_format

        log.debug(
            "openai_compat.complete_structured",
            model=self.model,
            response_model=response_model.__name__,
        )

        start = time.monotonic()
        try:
            data = await self._post(payload)
        except httpx.HTTPStatusError as exc:
            if not 400 <= exc.response.status_code < 500:
                raise  # 5xx is a transport problem, not a capability problem
            log.info(
                "openai_compat.json_schema_unsupported, falling back to prompt schema",
                model=self.model,
                status=exc.response.status_code,
            )
            data = await self._post(
                self._prompt_schema_payload(messages, schema, temperature, max_tokens)
            )

        response = self._to_response(data, int((time.monotonic() - start) * 1000))
        return StructuredCompletion(
            parsed=self._parse_structured(response_model, response),
            response=response,
        )

    def _prompt_schema_payload(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        """Build the fallback payload with the schema injected into the system prompt."""
        json_instruction = (
            "Respond ONLY with one valid JSON object that satisfies the schema below. "
            "Do not return the schema, prose, markdown, or explanations. "
            f"Schema: {json.dumps(schema)}"
        )
        augmented = list(messages)
        if augmented and augmented[0]["role"] == "system":
            augmented[0] = {
                "role": "system",
                "content": augmented[0]["content"] + "\n\n" + json_instruction,
            }
        else:
            augmented.insert(0, {"role": "system", "content": json_instruction})
        return self._base_payload(augmented, temperature, max_tokens)

    def _parse_structured(self, response_model: type[T], response: CompletionResponse) -> T:
        try:
            return validate_with_light_repair(response_model, response.content)
        except ValidationError as exc:
            if response.finish_reason == "length":
                raise LLMTruncationError(
                    f"{response_model.__name__} generation hit max_tokens",
                    raw_content=response.content,
                    response=response,
                ) from exc
            raise LLMValidationError(
                f"{response_model.__name__} validation failed",
                raw_content=response.content,
                validation_detail=str(exc),
                response=response,
            ) from exc

    def _clean_content(self, content: str) -> str:
        """Remove local-model reasoning wrappers that break downstream JSON parsing."""
        if not self.strip_reasoning_tags:
            return content

        cleaned = content.strip()
        if cleaned.startswith("<think>"):
            end = cleaned.find("</think>")
            if end != -1:
                cleaned = cleaned[end + len("</think>") :].strip()
        return cleaned

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
