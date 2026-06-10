"""Reliability layer wrapping every LLM call at the router chokepoint.

Responsibilities, in attempt order:
- cancellation: never start (or keep) a call after the job's cancel token trips
- endpoint concurrency limiting (one slot per in-flight request)
- transport retry with exponential backoff + jitter (timeouts on a separate,
  smaller budget -- a 40-minute timeout retried three times burns hours)
- truncation re-call: finish_reason == "length" -> grow max_tokens before
  resorting to brace-closing JSON repair
- validation feedback retry: re-prompt with the model's bad output and the
  pydantic error; the original messages stay byte-identical as a prefix so
  vLLM's prefix cache reuses the KV cache for the expensive prompt
- per-role fallback chain (opt-in via config)
- one LLMCallRecord per logical call for the transcript log
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from libs.adapters.llm.concurrency import (
    DEFAULT_HOSTED_MAX_CONCURRENT,
    DEFAULT_LOCAL_MAX_CONCURRENT,
    EndpointLimiter,
)
from libs.adapters.llm.errors import (
    LLMRetriesExhausted,
    LLMTransportError,
    LLMTruncationError,
    LLMValidationError,
    classify_transport_error,
)
from libs.adapters.llm.json_repair import validate_with_full_repair
from libs.core.logging import get_logger
from libs.core.run_context import CancelToken, get_cancel_token
from libs.schemas.model_gateway import CompletionResponse, StructuredCompletion

if TYPE_CHECKING:
    from libs.adapters.llm.base import LLMAdapter

log = get_logger(__name__)

_RETRY_POLICY_KEYS = (
    "transport_attempts",
    "timeout_attempts",
    "backoff_base_s",
    "backoff_max_s",
    "jitter_frac",
    "validation_attempts",
    "truncation_attempts",
    "max_tokens_growth",
    "max_tokens_ceiling",
    "feedback_output_cap_chars",
)


@dataclass(frozen=True)
class RetryPolicy:
    """Per-role retry budgets, resolved from models.yaml ``retry`` blocks."""

    transport_attempts: int = 3  # total attempts including the first
    timeout_attempts: int = 2  # timeouts budgeted separately (they're expensive)
    backoff_base_s: float = 2.0
    backoff_max_s: float = 60.0
    jitter_frac: float = 0.5
    validation_attempts: int = 2  # feedback re-prompts after the first failure
    truncation_attempts: int = 1  # re-calls with grown max_tokens
    max_tokens_growth: float = 2.0
    max_tokens_ceiling: int = 16384
    feedback_output_cap_chars: int = 8000

    @classmethod
    def from_role_config(cls, role_cfg: dict[str, Any]) -> RetryPolicy:
        retry_cfg = role_cfg.get("retry") or {}
        kwargs = {key: retry_cfg[key] for key in _RETRY_POLICY_KEYS if key in retry_cfg}
        return cls(**kwargs)

    def reduced_for_fallback(self) -> RetryPolicy:
        return replace(self, transport_attempts=2, timeout_attempts=1, validation_attempts=1)


@dataclass
class LLMCallRecord:
    """One row of LLM call telemetry, emitted per logical router call."""

    role: str
    provider: str
    model: str
    base_url: str | None
    request_kind: str  # "complete" | "structured"
    response_model: str | None
    messages: list[dict[str, str]]
    outcome: str  # success|validation_error|transport_error|timeout|truncated|cancelled
    attempts: int
    latency_ms: int
    fallback_used: bool = False
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_text: str | None = None
    error: str | None = None
    attempt_log: list[dict[str, Any]] = field(default_factory=list)


Recorder = Callable[[LLMCallRecord], Awaitable[None]]


class _EndpointExhausted(Exception):
    """Internal: one endpoint's budgets are spent; carries the last error."""

    def __init__(self, outcome: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.outcome = outcome
        self.cause = cause


def _cap_middle(text: str, cap: int) -> str:
    """Cap text by keeping head and tail (validation errors cite both ends)."""
    if len(text) <= cap:
        return text
    half = cap // 2
    return text[:half] + "\n[... output truncated for retry ...]\n" + text[-half:]


def _feedback_messages(
    original: list[dict[str, str]],
    bad_output: str,
    validation_detail: str,
    response_model_name: str,
    cap_chars: int,
) -> list[dict[str, str]]:
    """Build the feedback re-prompt. ``original`` stays byte-identical as prefix."""
    return [
        *original,
        {"role": "assistant", "content": _cap_middle(bad_output, cap_chars)},
        {
            "role": "user",
            "content": (
                f"Your previous response failed validation for {response_model_name}:\n"
                f"{validation_detail[:2000]}\n"
                "Return ONLY a corrected JSON object that satisfies the schema. "
                "No prose, no markdown."
            ),
        },
    ]


class ReliableLLMClient:
    """Budgeted retry/cancellation/fallback orchestration over dumb adapters."""

    def __init__(
        self,
        *,
        adapter_for_config: Callable[[dict[str, Any]], LLMAdapter],
        provider_config: Callable[[str], dict[str, Any]],
        limiter: EndpointLimiter,
        recorder: Recorder | None = None,
    ) -> None:
        self._adapter_for_config = adapter_for_config
        self._provider_config = provider_config
        self._limiter = limiter
        self._recorder = recorder

    # ------------------------------------------------------------------ public

    async def complete(
        self,
        *,
        role: str,
        role_cfg: dict[str, Any],
        fallback_cfg: dict[str, Any] | None,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        record = self._new_record(role, role_cfg, "complete", None, messages)
        start = time.monotonic()
        try:
            response = await self._with_fallback(
                role_cfg,
                fallback_cfg,
                record,
                lambda cfg, policy: self._run_complete(
                    cfg, policy, record, messages, temperature, max_tokens
                ),
            )
        except BaseException as exc:
            await self._finalize(record, start, error=exc)
            raise
        record.outcome = "success"
        record.finish_reason = response.finish_reason
        record.input_tokens = response.input_tokens
        record.output_tokens = response.output_tokens
        record.response_text = response.content
        response.attempts = record.attempts
        await self._finalize(record, start)
        return response

    async def complete_structured[T: BaseModel](
        self,
        *,
        role: str,
        role_cfg: dict[str, Any],
        fallback_cfg: dict[str, Any] | None,
        messages: list[dict[str, str]],
        response_model: type[T],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> StructuredCompletion[T]:
        record = self._new_record(role, role_cfg, "structured", response_model.__name__, messages)
        start = time.monotonic()
        try:
            structured = await self._with_fallback(
                role_cfg,
                fallback_cfg,
                record,
                lambda cfg, policy: self._run_structured(
                    cfg, policy, record, messages, response_model, temperature, max_tokens
                ),
            )
        except BaseException as exc:
            await self._finalize(record, start, error=exc)
            raise
        record.outcome = "success"
        record.finish_reason = structured.response.finish_reason
        record.input_tokens = structured.response.input_tokens
        record.output_tokens = structured.response.output_tokens
        record.response_text = structured.response.content
        structured.response.attempts = record.attempts
        await self._finalize(record, start)
        return structured

    # ----------------------------------------------------------- orchestration

    async def _with_fallback[R](
        self,
        role_cfg: dict[str, Any],
        fallback_cfg: dict[str, Any] | None,
        record: LLMCallRecord,
        run: Callable[[dict[str, Any], RetryPolicy], Coroutine[Any, Any, R]],
    ) -> R:
        policy = RetryPolicy.from_role_config(role_cfg)
        try:
            return await run(role_cfg, policy)
        except _EndpointExhausted as exhausted:
            if fallback_cfg is None:
                raise LLMRetriesExhausted(
                    f"{record.role}: {exhausted.outcome} after {record.attempts} attempts: "
                    f"{exhausted.cause}",
                    cause=exhausted.cause,
                ) from exhausted.cause
            log.warning(
                "llm_reliability.falling_back",
                role=record.role,
                primary_model=role_cfg.get("model"),
                fallback_model=fallback_cfg.get("model"),
                outcome=exhausted.outcome,
            )
            record.fallback_used = True
            record.provider = str(fallback_cfg.get("provider", record.provider))
            record.model = str(fallback_cfg.get("model", record.model))
            try:
                return await run(fallback_cfg, policy.reduced_for_fallback())
            except _EndpointExhausted as fb_exhausted:
                raise LLMRetriesExhausted(
                    f"{record.role}: fallback also exhausted "
                    f"({fb_exhausted.outcome}): {fb_exhausted.cause}",
                    cause=fb_exhausted.cause,
                ) from fb_exhausted.cause

    async def _run_complete(
        self,
        cfg: dict[str, Any],
        policy: RetryPolicy,
        record: LLMCallRecord,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
    ) -> CompletionResponse:
        adapter = self._adapter_for_config(cfg)
        endpoint_key, max_concurrent = self._endpoint_limits(cfg)
        token = get_cancel_token()
        budgets = _Budgets(policy)
        current_max_tokens = max_tokens if max_tokens is not None else cfg.get("max_tokens", 4096)
        truncations = 0

        while True:
            response = await self._attempt(
                record,
                budgets,
                policy,
                token,
                endpoint_key,
                max_concurrent,
                lambda mt=current_max_tokens: adapter.complete(
                    messages, temperature=temperature, max_tokens=mt
                ),
            )
            if response is None:
                continue  # transport retry scheduled
            if (
                response.finish_reason == "length"
                and truncations < policy.truncation_attempts
                and current_max_tokens < policy.max_tokens_ceiling
            ):
                truncations += 1
                current_max_tokens = min(
                    policy.max_tokens_ceiling,
                    int(current_max_tokens * policy.max_tokens_growth),
                )
                record.attempt_log.append({"attempt": record.attempts, "kind": "truncation_recall"})
                continue
            return response

    async def _run_structured[T: BaseModel](
        self,
        cfg: dict[str, Any],
        policy: RetryPolicy,
        record: LLMCallRecord,
        messages: list[dict[str, str]],
        response_model: type[T],
        temperature: float | None,
        max_tokens: int | None,
    ) -> StructuredCompletion[T]:
        adapter = self._adapter_for_config(cfg)
        endpoint_key, max_concurrent = self._endpoint_limits(cfg)
        token = get_cancel_token()
        budgets = _Budgets(policy)
        current_max_tokens = max_tokens if max_tokens is not None else cfg.get("max_tokens", 4096)
        current_messages = messages
        truncations = 0
        validations = 0

        while True:
            try:
                result = await self._attempt(
                    record,
                    budgets,
                    policy,
                    token,
                    endpoint_key,
                    max_concurrent,
                    lambda msgs=current_messages, mt=current_max_tokens: (
                        adapter.complete_structured(
                            msgs, response_model, temperature=temperature, max_tokens=mt
                        )
                    ),
                )
            except LLMTruncationError as exc:
                if truncations < policy.truncation_attempts and current_max_tokens < (
                    policy.max_tokens_ceiling
                ):
                    truncations += 1
                    current_max_tokens = min(
                        policy.max_tokens_ceiling,
                        int(current_max_tokens * policy.max_tokens_growth),
                    )
                    record.attempt_log.append(
                        {"attempt": record.attempts, "kind": "truncation_recall"}
                    )
                    log.info(
                        "llm_reliability.truncation_recall",
                        role=record.role,
                        new_max_tokens=current_max_tokens,
                    )
                    continue
                # Last resort: brace-closing repair on the truncated output.
                try:
                    parsed = validate_with_full_repair(response_model, exc.raw_content)
                    record.attempt_log.append(
                        {"attempt": record.attempts, "kind": "truncation_repaired"}
                    )
                    log.warning(
                        "llm_reliability.truncation_repaired",
                        role=record.role,
                        model=record.model,
                    )
                    return StructuredCompletion(parsed=parsed, response=exc.response)
                except ValidationError:
                    if validations < policy.validation_attempts:
                        validations += 1
                        current_messages = _feedback_messages(
                            messages,
                            exc.raw_content,
                            "Output was truncated mid-generation and could not be parsed. "
                            "Produce a more compact response that fits.",
                            response_model.__name__,
                            policy.feedback_output_cap_chars,
                        )
                        continue
                    raise _EndpointExhausted("truncated", exc) from exc
            except LLMValidationError as exc:
                if validations < policy.validation_attempts:
                    validations += 1
                    current_messages = _feedback_messages(
                        messages,
                        exc.raw_content,
                        exc.validation_detail,
                        response_model.__name__,
                        policy.feedback_output_cap_chars,
                    )
                    record.attempt_log.append(
                        {"attempt": record.attempts, "kind": "validation_feedback"}
                    )
                    log.info(
                        "llm_reliability.validation_feedback_retry",
                        role=record.role,
                        attempt=validations,
                    )
                    continue
                raise _EndpointExhausted("validation_error", exc) from exc
            if result is None:
                continue  # transport retry scheduled
            return result

    async def _attempt[R](
        self,
        record: LLMCallRecord,
        budgets: _Budgets,
        policy: RetryPolicy,
        token: CancelToken | None,
        endpoint_key: str | None,
        max_concurrent: int,
        call: Callable[[], Coroutine[Any, Any, R]],
    ) -> R | None:
        """Run one provider attempt.

        Returns the result, returns None when a transport retry was scheduled
        (backoff already slept), or raises: typed parse errors pass through to
        the structured loop; exhausted/cancelled/non-retryable errors raise.
        """
        if token is not None:
            token.raise_if_cancelled()
        record.attempts += 1
        attempt_start = time.monotonic()
        try:
            async with self._limiter.limit(endpoint_key, max_concurrent):
                if token is not None:
                    token.raise_if_cancelled()
                return await self._race_cancel(call(), token)
        except (LLMTruncationError, LLMValidationError):
            raise  # structured loop handles budgets for these
        except Exception as exc:
            transport = classify_transport_error(exc)
            if transport is None:
                raise  # programming error, never retry
            latency_ms = int((time.monotonic() - attempt_start) * 1000)
            record.attempt_log.append(
                {
                    "attempt": record.attempts,
                    "kind": "timeout" if _is_timeout(transport) else "transport_error",
                    "error": str(transport)[:500],
                    "latency_ms": latency_ms,
                }
            )
            if not transport.retryable:
                raise transport from exc
            if not budgets.consume(transport):
                outcome = "timeout" if _is_timeout(transport) else "transport_error"
                raise _EndpointExhausted(outcome, transport) from exc
            await self._backoff(budgets.spent_retries, policy, token)
            return None

    async def _race_cancel[R](self, coro: Coroutine[Any, Any, R], token: CancelToken | None) -> R:
        """Race the in-flight call against the cancel token.

        On cancel: the call task is cancelled, which closes the HTTP request;
        well-behaved servers (vLLM, llama.cpp) abort generation on client
        disconnect, freeing the GPU.
        """
        if token is None:
            return await coro
        call_task = asyncio.ensure_future(coro)
        watch_task = asyncio.ensure_future(token.wait())
        try:
            done, _ = await asyncio.wait(
                {call_task, watch_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if call_task in done:
                return call_task.result()
            call_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await call_task
            token.raise_if_cancelled()
            raise AssertionError("unreachable: watcher resolved without tripped token")
        finally:
            watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watch_task

    async def _backoff(
        self, retry_number: int, policy: RetryPolicy, token: CancelToken | None
    ) -> None:
        delay = min(policy.backoff_max_s, policy.backoff_base_s * (2 ** (retry_number - 1)))
        delay *= 1 + random.uniform(-policy.jitter_frac, policy.jitter_frac)
        delay = max(0.0, delay)
        log.info("llm_reliability.backoff", delay_s=round(delay, 2))
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if token is not None:
                token.raise_if_cancelled()
            await asyncio.sleep(min(0.5, max(0.0, deadline - time.monotonic())))

    # ----------------------------------------------------------------- helpers

    def _endpoint_limits(self, cfg: dict[str, Any]) -> tuple[str | None, int]:
        provider = str(cfg.get("provider", ""))
        provider_cfg = self._provider_config(provider) if provider else {}
        provider_type = cfg.get("provider_type") or provider_cfg.get("type", provider)
        base_url = cfg.get("base_url") or provider_cfg.get("base_url")
        key = base_url or provider or None
        default = (
            DEFAULT_LOCAL_MAX_CONCURRENT
            if provider_type == "openai_compatible"
            else DEFAULT_HOSTED_MAX_CONCURRENT
        )
        max_concurrent = int(
            cfg.get("max_concurrent") or provider_cfg.get("max_concurrent_requests") or default
        )
        return key, max_concurrent

    def _new_record(
        self,
        role: str,
        role_cfg: dict[str, Any],
        request_kind: str,
        response_model: str | None,
        messages: list[dict[str, str]],
    ) -> LLMCallRecord:
        provider = str(role_cfg.get("provider", ""))
        provider_cfg = self._provider_config(provider) if provider else {}
        return LLMCallRecord(
            role=role,
            provider=provider,
            model=str(role_cfg.get("model", "")),
            base_url=role_cfg.get("base_url") or provider_cfg.get("base_url"),
            request_kind=request_kind,
            response_model=response_model,
            messages=messages,
            outcome="error",
            attempts=0,
            latency_ms=0,
        )

    async def _finalize(
        self, record: LLMCallRecord, start: float, error: BaseException | None = None
    ) -> None:
        record.latency_ms = int((time.monotonic() - start) * 1000)
        if error is not None:
            record.error = str(error)[:2000]
            record.outcome = _outcome_for_error(error)
        if self._recorder is None:
            return
        try:
            await self._recorder(record)
        except Exception:
            log.exception("llm_reliability.recorder_failed", role=record.role)


class _Budgets:
    """Mutable transport/timeout retry counters for one endpoint run."""

    def __init__(self, policy: RetryPolicy) -> None:
        self._policy = policy
        self.transport_failures = 0
        self.timeout_failures = 0
        self.spent_retries = 0

    def consume(self, transport: LLMTransportError) -> bool:
        """Record a failed attempt; False when no further attempt is allowed.

        ``transport_attempts``/``timeout_attempts`` are total attempts: with
        N attempts allowed, the Nth failure exhausts the budget.
        """
        self.spent_retries += 1
        if _is_timeout(transport):
            self.timeout_failures += 1
            return self.timeout_failures < self._policy.timeout_attempts
        self.transport_failures += 1
        return self.transport_failures < self._policy.transport_attempts


def _is_timeout(transport: LLMTransportError) -> bool:
    from libs.adapters.llm.errors import LLMTimeoutError

    return isinstance(transport, LLMTimeoutError)


def _outcome_for_error(error: BaseException) -> str:
    from libs.core.errors import OperationCancelled, OperatorTimeout

    if isinstance(error, (OperationCancelled, OperatorTimeout)):
        return "cancelled"
    if isinstance(error, LLMRetriesExhausted):
        cause = error.cause
        if isinstance(cause, LLMValidationError):
            return "validation_error"
        if isinstance(cause, LLMTruncationError):
            return "truncated"
        if cause is not None and isinstance(cause, LLMTransportError) and _is_timeout(cause):
            return "timeout"
        return "transport_error"
    if isinstance(error, LLMTransportError):
        return "timeout" if _is_timeout(error) else "transport_error"
    if isinstance(error, LLMValidationError):
        return "validation_error"
    if isinstance(error, LLMTruncationError):
        return "truncated"
    return "error"
