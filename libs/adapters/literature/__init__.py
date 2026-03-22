"""Literature source adapter interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class SourceQuery(BaseModel):
    """Query parameters for literature source search."""

    keywords: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    date_from: str | None = None
    date_until: str | None = None
    max_results: int = 100


class RawPaperRecord(BaseModel):
    """Normalised paper record returned by any source adapter."""

    external_id: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    publication_date: str | None = None
    source_url: str | None = None
    pdf_url: str | None = None
    source_type: str  # arxiv, internal_corpus, external
    metadata_extra: dict[str, Any] = Field(default_factory=dict)


class FetchResult(BaseModel):
    """Result of a full-text fetch operation."""

    content_type: str  # html or pdf
    artifact_path: str
    byte_count: int
    fetch_reason: str


class LiteratureSourceAdapter(ABC):
    """Abstract adapter for literature source search."""

    @abstractmethod
    def search(self, query: SourceQuery) -> list[RawPaperRecord]:
        """Search for papers matching the query."""
