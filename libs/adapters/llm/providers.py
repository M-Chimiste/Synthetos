"""Provider-specific request/response adapters for LLM APIs.

Each provider (openai_compatible, anthropic, google) has pure functions for:
- Building request payloads
- Building HTTP headers
- Constructing the endpoint URL
- Extracting content from the response

No vendor SDKs — just httpx request construction.
``openai_compatible`` covers OpenAI, vLLM, LM Studio, Ollama, and any server
exposing the OpenAI-compatible ``/v1/chat/completions`` endpoint.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# OpenAI-compatible (OpenAI, vLLM, LM Studio, Ollama, etc.)
# ---------------------------------------------------------------------------


def _build_openai_payload(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _build_openai_headers(api_key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _get_openai_endpoint(base_url: str, _model: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _extract_openai_content(response_data: dict) -> str:
    choices = response_data.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


# ---------------------------------------------------------------------------
# Anthropic (Messages API)
# ---------------------------------------------------------------------------

_ANTHROPIC_VERSION = "2023-06-01"


def _build_anthropic_payload(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> dict[str, Any]:
    # Anthropic separates system from user/assistant messages
    system_text = ""
    conversation: list[dict[str, str]] = []
    for msg in messages:
        if msg.get("role") == "system":
            system_text += msg.get("content", "") + "\n"
        else:
            conversation.append(msg)

    # Anthropic JSON mode: add prefill in assistant turn
    if json_mode and (
        not conversation or conversation[-1].get("role") != "assistant"
    ):
        conversation.append({"role": "assistant", "content": "{"})

    payload: dict[str, Any] = {
        "model": model,
        "messages": conversation,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_text.strip():
        payload["system"] = system_text.strip()
    return payload


def _build_anthropic_headers(api_key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "anthropic-version": _ANTHROPIC_VERSION,
    }
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _get_anthropic_endpoint(base_url: str, _model: str) -> str:
    return f"{base_url.rstrip('/')}/messages"


def _extract_anthropic_content(response_data: dict) -> str:
    content_blocks = response_data.get("content", [])
    if not content_blocks:
        return ""
    # Concatenate all text blocks
    parts = [
        block.get("text", "")
        for block in content_blocks
        if block.get("type") == "text"
    ]
    return "".join(parts)


# ---------------------------------------------------------------------------
# Google (Gemini / Generative Language API)
# ---------------------------------------------------------------------------


def _build_google_payload(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> dict[str, Any]:
    # Convert OpenAI-style messages to Google format
    contents: list[dict[str, Any]] = []
    system_instruction = None

    for msg in messages:
        role = msg.get("role", "user")
        text = msg.get("content", "")
        if role == "system":
            system_instruction = text
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": text}]})
        else:
            contents.append({"role": "user", "parts": [{"text": text}]})

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}],
        }
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"
    return payload


def _build_google_headers(api_key: str | None) -> dict[str, str]:
    # Google uses API key as query param, not header, but we include
    # Content-Type for consistency
    headers: dict[str, str] = {"Content-Type": "application/json"}
    return headers


def _get_google_endpoint(base_url: str, model: str) -> str:
    return f"{base_url.rstrip('/')}/models/{model}:generateContent"


def _extract_google_content(response_data: dict) -> str:
    candidates = response_data.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        return ""
    return parts[0].get("text", "")


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------

_PAYLOAD_BUILDERS = {
    "openai_compatible": _build_openai_payload,
    "anthropic": _build_anthropic_payload,
    "google": _build_google_payload,
}

_HEADER_BUILDERS = {
    "openai_compatible": _build_openai_headers,
    "anthropic": _build_anthropic_headers,
    "google": _build_google_headers,
}

_ENDPOINT_BUILDERS = {
    "openai_compatible": _get_openai_endpoint,
    "anthropic": _get_anthropic_endpoint,
    "google": _get_google_endpoint,
}

_CONTENT_EXTRACTORS = {
    "openai_compatible": _extract_openai_content,
    "anthropic": _extract_anthropic_content,
    "google": _extract_google_content,
}

SUPPORTED_PROVIDERS = frozenset(_PAYLOAD_BUILDERS.keys())


def build_payload(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> dict[str, Any]:
    builder = _PAYLOAD_BUILDERS.get(provider)
    if builder is None:
        raise ValueError(f"Unsupported provider: {provider!r}")
    return builder(model, messages, temperature, max_tokens, json_mode)


def build_headers(provider: str, api_key: str | None) -> dict[str, str]:
    builder = _HEADER_BUILDERS.get(provider)
    if builder is None:
        raise ValueError(f"Unsupported provider: {provider!r}")
    return builder(api_key)


def get_endpoint(
    provider: str, base_url: str, model: str,
) -> str:
    builder = _ENDPOINT_BUILDERS.get(provider)
    if builder is None:
        raise ValueError(f"Unsupported provider: {provider!r}")
    return builder(base_url, model)


def extract_content(provider: str, response_data: dict) -> str:
    extractor = _CONTENT_EXTRACTORS.get(provider)
    if extractor is None:
        raise ValueError(f"Unsupported provider: {provider!r}")
    return extractor(response_data)


def get_query_params(provider: str, api_key: str | None) -> dict[str, str]:
    """Return query parameters for providers that use them (e.g., Google)."""
    if provider == "google" and api_key:
        return {"key": api_key}
    return {}
