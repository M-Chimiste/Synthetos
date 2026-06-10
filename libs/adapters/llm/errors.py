"""Typed LLM call errors and provider exception classification.

The reliability layer drives its retry budgets off these types:
transport errors (retryable or not), truncation (finish_reason == "length"),
and validation failures (parse/schema mismatch, eligible for feedback
re-prompts).
"""

from __future__ import annotations

import anthropic
import httpx
import openai
from google.genai import errors as google_errors

from libs.core.errors import register_transient
from libs.schemas.model_gateway import CompletionResponse

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class LLMCallError(Exception):
    """Base class for LLM call failures."""


class LLMTransportError(LLMCallError):
    """Connection error, retryable HTTP status, or timeout."""

    def __init__(self, message: str, *, retryable: bool, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.cause = cause


class LLMTimeoutError(LLMTransportError):
    """Request exceeded the configured timeout. Retried on a separate budget."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message, retryable=True, cause=cause)


class LLMValidationError(LLMCallError):
    """Structured output failed pydantic validation after light repair."""

    def __init__(
        self,
        message: str,
        *,
        raw_content: str,
        validation_detail: str,
        response: CompletionResponse,
    ) -> None:
        super().__init__(message)
        self.raw_content = raw_content
        self.validation_detail = validation_detail
        self.response = response


class LLMTruncationError(LLMCallError):
    """Generation hit max_tokens (finish_reason == "length") and strict parse failed."""

    def __init__(self, message: str, *, raw_content: str, response: CompletionResponse) -> None:
        super().__init__(message)
        self.raw_content = raw_content
        self.response = response


class LLMRetriesExhausted(LLMCallError):
    """All reliability-layer budgets (and any fallback) failed for one call."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


def classify_transport_error(exc: Exception) -> LLMTransportError | None:
    """Map provider/transport exceptions to LLMTransportError, or None if not transport."""
    if isinstance(exc, LLMTransportError):
        return exc

    # httpx (openai_compat adapter and SDK underpinnings)
    if isinstance(exc, httpx.TimeoutException):
        return LLMTimeoutError(f"request timed out: {exc}", cause=exc)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return LLMTransportError(
            f"HTTP {status}: {exc.response.text[:200]}",
            retryable=status in _RETRYABLE_STATUS,
            cause=exc,
        )
    if isinstance(exc, httpx.TransportError):
        return LLMTransportError(f"transport error: {exc}", retryable=True, cause=exc)

    # anthropic SDK
    if isinstance(exc, anthropic.APITimeoutError):
        return LLMTimeoutError(f"anthropic timeout: {exc}", cause=exc)
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMTransportError(f"anthropic connection error: {exc}", retryable=True, cause=exc)
    if isinstance(exc, anthropic.APIStatusError):
        return LLMTransportError(
            f"anthropic HTTP {exc.status_code}: {exc.message}",
            retryable=exc.status_code in _RETRYABLE_STATUS,
            cause=exc,
        )

    # openai SDK
    if isinstance(exc, openai.APITimeoutError):
        return LLMTimeoutError(f"openai timeout: {exc}", cause=exc)
    if isinstance(exc, openai.APIConnectionError):
        return LLMTransportError(f"openai connection error: {exc}", retryable=True, cause=exc)
    if isinstance(exc, openai.APIStatusError):
        return LLMTransportError(
            f"openai HTTP {exc.status_code}: {exc.message}",
            retryable=exc.status_code in _RETRYABLE_STATUS,
            cause=exc,
        )

    # google-genai SDK
    if isinstance(exc, google_errors.APIError):
        code = exc.code if isinstance(exc.code, int) else 0
        return LLMTransportError(
            f"google HTTP {code}: {exc.message}",
            retryable=code in _RETRYABLE_STATUS,
            cause=exc,
        )

    return None


def normalize_finish_reason(raw: str | None) -> str | None:
    """Normalize provider finish reasons to a small shared vocabulary."""
    if raw is None:
        return None
    mapping = {
        # openai-compatible
        "stop": "stop",
        "length": "length",
        "tool_calls": "tool_use",
        "function_call": "tool_use",
        "content_filter": "content_filter",
        # anthropic
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_use",
        "refusal": "content_filter",
        # google
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
    }
    return mapping.get(raw, "other")


# Job-level classification: a job that died because the LLM stack exhausted
# its internal budgets is worth one fresh job-level attempt (local inference
# flakiness dominates here); non-retryable transport errors are excluded by
# the reliability layer never wrapping them in LLMRetriesExhausted.
register_transient(LLMRetriesExhausted, LLMTimeoutError)
