"""Ingestion adapter protocol and shared DTOs."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class NormalizedSection(BaseModel):
    """A section extracted from the paper's full text."""

    heading: str
    level: int = Field(ge=0, le=10)
    content: str
    page_range: list[int] | None = None


class NormalizedFigure(BaseModel):
    """A figure extracted from the paper."""

    id: str
    caption: str
    page: int | None = None
    content_description: str | None = None


class NormalizedTable(BaseModel):
    """A table extracted from the paper."""

    id: str
    caption: str
    page: int | None = None
    content_description: str | None = None


class NormalizedEquation(BaseModel):
    """An equation extracted from the paper."""

    id: str
    latex: str
    context: str | None = None
    page: int | None = None


class QualityAssessment(BaseModel):
    """Quality assessment for an ingested document."""

    structure_preserved: bool
    section_count: int = 0
    figure_count: int = 0
    table_count: int = 0
    equation_count: int = 0
    quality_score: float = Field(ge=0.0, le=1.0)
    quality_warnings: list[str] = Field(default_factory=list)


class IngestionResult(BaseModel):
    """Result of fetching and normalizing a paper's full text."""

    content: str
    normalized_sections: list[NormalizedSection] = Field(default_factory=list)
    normalized_figures: list[NormalizedFigure] = Field(default_factory=list)
    normalized_tables: list[NormalizedTable] = Field(default_factory=list)
    normalized_equations: list[NormalizedEquation] = Field(default_factory=list)
    fetch_method: str  # "html" or "pdf_docling"
    source_url: str
    quality_assessment: QualityAssessment
    fetch_duration_ms: int = 0
    metadata: dict[str, Any] | None = None


class IngestionError(Exception):
    """Raised when full-text ingestion fails."""


class IngestionQualityLow(IngestionError):
    """Raised when HTML quality is below the configured threshold."""

    def __init__(self, quality_score: float, threshold: float) -> None:
        self.quality_score = quality_score
        self.threshold = threshold
        super().__init__(
            f"HTML quality {quality_score:.2f} below threshold {threshold:.2f}"
        )


@runtime_checkable
class IngestionAdapter(Protocol):
    """Protocol that all paper ingestion adapters must satisfy."""

    name: str

    async def fetch_fulltext(
        self,
        paper_url: str,
        pdf_url: str | None = None,
    ) -> IngestionResult:
        """Fetch and normalize the paper's full text."""
        ...

    async def close(self) -> None:
        """Release any held resources."""
        ...
