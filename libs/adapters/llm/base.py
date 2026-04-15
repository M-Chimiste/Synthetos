"""Base protocol for LLM adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from libs.schemas.model_gateway import CompletionResponse

T = TypeVar("T")


@runtime_checkable
class LLMAdapter(Protocol):
    """Protocol that all LLM adapters must satisfy.

    Adapters provide two core operations:
    - complete: free-form text completion
    - complete_structured: completion parsed into a typed Pydantic model
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
    ) -> T:
        """Generate a chat completion and parse it into a Pydantic model instance."""
        ...

    async def close(self) -> None:
        """Release any underlying client resources."""
        ...
