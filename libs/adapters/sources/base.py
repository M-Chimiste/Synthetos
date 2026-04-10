"""Base protocol and DTOs for discovery source adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SourceQuery(BaseModel):
    """Parameters describing one source query.

    Adapters may ignore fields they do not support.
    """

    text: str = Field(min_length=1)
    top_k: int = Field(default=200, ge=1, le=2000)
    categories: list[str] = Field(default_factory=list)
    year_min: int | None = None
    year_max: int | None = None


class SourceHit(BaseModel):
    """One paper returned by a source adapter.

    The shape is the union of fields needed to populate a ``paper_cards``
    row.  Adapters return whatever they have; missing fields are normalized
    later by the discovery layer.
    """

    source: str
    external_id: str
    title: str
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    published_at: datetime | None = None
    doi: str | None = None
    source_url: str | None = None
    pdf_url: str | None = None

    # Optional embedding (only set by sources that store one, e.g. internal corpus).
    embedding: list[float] | None = None

    # Optional first-stage scores produced by the source itself.
    bm25_score: float | None = None
    dense_score: float | None = None
    first_stage_score: float | None = None


@runtime_checkable
class SourceAdapter(Protocol):
    """Protocol that all discovery source adapters must satisfy."""

    name: str

    async def search(self, query: SourceQuery) -> list[SourceHit]:
        """Run one query and return ranked hits."""
        ...

    async def close(self) -> None:
        """Release any held resources (HTTP clients, sessions)."""
        ...
