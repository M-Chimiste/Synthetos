"""Pydantic schemas for the model gateway."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ModelRole(StrEnum):
    """Logical roles that map to specific provider/model configurations."""

    planning = "planning"
    retrieval_synthesis = "retrieval_synthesis"
    metadata_analysis = "metadata_analysis"
    coding = "coding"
    summarization = "summarization"
    evaluation = "evaluation"
    report_writing = "report_writing"
    paper_analysis = "paper_analysis"
    graph_extraction = "graph_extraction"
    paper_review = "paper_review"
    hypothesis_generation = "hypothesis_generation"
    protocol_drafting = "protocol_drafting"
    remediation = "remediation"
    context_compression = "context_compression"


class CompletionRequest(BaseModel):
    """Request for an LLM completion."""

    messages: list[dict[str, str]] = Field(
        ..., description="Chat messages with 'role' and 'content' keys."
    )
    model_role: ModelRole = Field(..., description="Logical role for model routing.")
    temperature: float | None = Field(default=None, description="Sampling temperature override.")
    max_tokens: int | None = Field(default=None, description="Max output tokens override.")
    response_model: str | None = Field(
        default=None,
        description="Fully qualified name of a Pydantic model for structured output.",
    )


class CompletionResponse(BaseModel):
    """Response from an LLM completion."""

    content: str
    model: str
    provider: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    structured_output: Any | None = None
    # Normalized across providers: "stop" | "length" | "tool_use" |
    # "content_filter" | "other"; None when the provider omitted it.
    finish_reason: str | None = None
    # Wall-clock of the single provider request, measured in the adapter.
    latency_ms: int | None = None
    # Total attempts behind this response; set by the reliability layer.
    attempts: int = 1


@dataclass
class StructuredCompletion[T]:
    """A parsed structured output plus the response metadata behind it."""

    parsed: T
    response: CompletionResponse


class EmbeddingRequest(BaseModel):
    """Request for text embeddings."""

    texts: list[str] = Field(..., min_length=1)


class EmbeddingResponse(BaseModel):
    """Response containing computed embeddings."""

    embeddings: list[list[float]]
    model: str
    dimensions: int
