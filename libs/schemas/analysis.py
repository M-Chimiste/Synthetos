"""Pydantic schemas for the Phase 2 analysis pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Ingestion DTOs
# ---------------------------------------------------------------------------


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


class IngestedDocumentRead(BaseModel):
    """Read schema for a persisted full-text artifact."""

    model_config = {"from_attributes": True}

    id: UUID
    analysis_session_id: UUID
    paper_card_id: UUID
    fetch_method: str
    source_url: str
    normalized_sections: list[dict[str, Any]] | None
    normalized_figures: list[dict[str, Any]] | None
    normalized_tables: list[dict[str, Any]] | None
    normalized_equations: list[dict[str, Any]] | None
    quality_assessment: dict[str, Any] | None
    fetch_duration_ms: int | None
    content_hash: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Analysis session
# ---------------------------------------------------------------------------


class AnalysisBudget(BaseModel):
    """Per-session analysis budget controls."""

    max_chunks: int = Field(default=500, ge=1, le=5000)
    graph_extraction_concurrency: int = Field(default=4, ge=1, le=16)
    evidence_extraction_concurrency: int = Field(default=4, ge=1, le=16)
    html_quality_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class AnalysisSessionStartRequest(BaseModel):
    """Body posted to ``POST /papers/{paper_card_id}/analyze``."""

    budget: AnalysisBudget = Field(default_factory=AnalysisBudget)


class AnalysisSessionRead(BaseModel):
    """Read schema for an analysis session."""

    model_config = {"from_attributes": True}

    id: UUID
    cycle_id: UUID
    charter_id: UUID
    paper_card_id: UUID
    status: str
    budget: dict[str, Any] | None
    stats: dict[str, Any] | None
    step_log: list[Any] | None
    report_artifact_path: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AnalysisSessionStartResponse(BaseModel):
    """Returned by ``POST /papers/{paper_card_id}/analyze``."""

    session: AnalysisSessionRead
    job_id: UUID


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


class PaperChunkRead(BaseModel):
    """Read schema for a paper chunk."""

    model_config = {"from_attributes": True}

    id: UUID
    analysis_session_id: UUID
    paper_card_id: UUID
    chunk_type: str
    section_path: str | None
    ordinal: int
    content: str
    content_hash: str
    chunk_metadata: dict[str, Any] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class GraphNodeRead(BaseModel):
    """Read schema for a graph node."""

    model_config = {"from_attributes": True}

    id: UUID
    analysis_session_id: UUID
    paper_card_id: UUID
    node_type: str
    label: str
    description: str | None
    properties: dict[str, Any] | None
    provenance: dict[str, Any] | None
    created_at: datetime


class GraphEdgeRead(BaseModel):
    """Read schema for a graph edge."""

    model_config = {"from_attributes": True}

    id: UUID
    analysis_session_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    edge_type: str
    properties: dict[str, Any] | None
    provenance: dict[str, Any] | None
    confidence: float | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


class CoverageDetail(BaseModel):
    """Coverage stats for one artifact type (sections, figures, etc.)."""

    total: int = 0
    covered: int = 0
    missing: list[str] = Field(default_factory=list)


class CoverageDiagnosticRead(BaseModel):
    """Read schema for coverage diagnostics."""

    model_config = {"from_attributes": True}

    id: UUID
    analysis_session_id: UUID
    section_coverage: dict[str, Any] | None
    figure_coverage: dict[str, Any] | None
    table_coverage: dict[str, Any] | None
    equation_coverage: dict[str, Any] | None
    unlinked_artifacts: list[str] | None
    warnings: list[str] | None
    overall_score: float
    created_at: datetime


# ---------------------------------------------------------------------------
# Analysis packet
# ---------------------------------------------------------------------------


class PaperAnalysisPacketRead(BaseModel):
    """Read schema for the canonical analysis packet."""

    model_config = {"from_attributes": True}

    id: UUID
    analysis_session_id: UUID
    paper_card_id: UUID
    charter_id: UUID
    summary: str
    key_contributions: list[str] | None
    methods_used: list[dict[str, Any]] | None
    datasets_referenced: list[dict[str, Any]] | None
    reproducibility_notes: dict[str, Any] | None
    graph_summary: dict[str, Any] | None
    coverage_snapshot: dict[str, Any] | None
    chunk_count: int
    node_count: int
    edge_count: int
    analysis_depth: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Review artifact
# ---------------------------------------------------------------------------


class PaperReviewArtifactRead(BaseModel):
    """Read schema for the advisory review artifact."""

    model_config = {"from_attributes": True}

    id: UUID
    analysis_packet_id: UUID
    paper_card_id: UUID
    strengths: list[str] | None
    weaknesses: list[str] | None
    open_questions: list[str] | None
    critique: str | None
    scores: dict[str, Any] | None
    reading_priority: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Evidence cards
# ---------------------------------------------------------------------------


class ContradictionFlag(BaseModel):
    """One contradiction entry linking to another evidence card."""

    evidence_id: UUID
    reason: str
    model_confidence: float = Field(ge=0.0, le=1.0)


class EvidenceCardRead(BaseModel):
    """Read schema for an evidence card."""

    model_config = {"from_attributes": True}

    id: UUID
    charter_id: UUID
    cycle_id: UUID
    paper_card_id: UUID
    analysis_packet_id: UUID | None
    evidence_type: str
    claim: str
    supporting_text: str | None
    source_chunk_ids: list[str] | None
    source_graph_node_ids: list[str] | None
    confidence: float
    analysis_depth: str
    contradiction_flags: dict[str, Any] | None
    redundancy_group: str | None
    extra_metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class EvidenceCardCreate(BaseModel):
    """Body for manual evidence creation."""

    paper_card_id: UUID
    evidence_type: str = Field(
        pattern="^(finding|method_claim|dataset_availability|limitation|comparison)$",
    )
    claim: str = Field(min_length=1, max_length=4000)
    supporting_text: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    analysis_depth: str = Field(default="metadata", pattern="^(metadata|full)$")


# ---------------------------------------------------------------------------
# Graph-aware QA
# ---------------------------------------------------------------------------


class ChunkRef(BaseModel):
    """Reference to a supporting chunk in a QA answer."""

    chunk_id: UUID
    section_path: str | None = None
    ordinal: int | None = None
    snippet: str | None = None


class NodeRef(BaseModel):
    """Reference to a supporting graph node in a QA answer."""

    node_id: UUID
    node_type: str
    label: str


class QARequest(BaseModel):
    """Body for graph-aware QA."""

    question: str = Field(min_length=1, max_length=2000)
    max_chunks: int = Field(default=10, ge=1, le=50)
    expand_graph: bool = True


class QAResponse(BaseModel):
    """Response from graph-aware QA."""

    answer: str
    supporting_chunks: list[ChunkRef] = Field(default_factory=list)
    supporting_nodes: list[NodeRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class LocateRequest(BaseModel):
    """Body for locating an entity in a paper."""

    entity_type: str = Field(pattern="^(concept|method|figure|table|equation|dataset)$")
    query: str = Field(min_length=1, max_length=500)


class LocateMatch(BaseModel):
    """One match from a locate query."""

    node: NodeRef
    chunks: list[ChunkRef] = Field(default_factory=list)


class LocateResponse(BaseModel):
    """Response from a locate query."""

    matches: list[LocateMatch] = Field(default_factory=list)


class AnalysisReportResponse(BaseModel):
    """Rendered analysis report bundle for a completed session."""

    model_config = ConfigDict(populate_by_name=True)

    session_id: UUID
    markdown: str | None = None
    json_payload: dict[str, Any] | None = Field(default=None, alias="json")
