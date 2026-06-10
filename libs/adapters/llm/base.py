"""Base protocol for LLM adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from pydantic import BaseModel

    from libs.schemas.model_gateway import CompletionResponse, StructuredCompletion

T = TypeVar("T", bound="BaseModel")


@runtime_checkable
class LLMAdapter(Protocol):
    """Protocol that all LLM adapters must satisfy.

    Adapters provide two core operations:
    - complete: free-form text completion
    - complete_structured: completion parsed into a typed Pydantic model

    Adapters are deliberately dumb: one provider request per call (plus
    capability fallbacks), light JSON repair only, typed errors
    (LLMValidationError / LLMTruncationError) on parse failure, and raw
    transport exceptions propagated. Retry policy lives in the reliability
    layer above.
    """

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResponse:
        """Generate a chat completion and return the response."""
        ...

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> StructuredCompletion[T]:
        """Generate a completion parsed into a Pydantic model, with response metadata."""
        ...

    async def close(self) -> None:
        """Release any underlying client resources."""
        ...
