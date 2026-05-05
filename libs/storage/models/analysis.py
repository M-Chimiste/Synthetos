"""Phase 2 analysis pipeline SQLAlchemy models.

These tables hold the per-paper state of a full-text analysis run:

* ``analysis_sessions`` -- one analysis pipeline run per paper.
* ``ingested_documents`` -- persisted full-text artifact with normalized structure.
* ``paper_chunks`` -- structure-aware chunks derived from ingested documents.
* ``graph_nodes`` / ``graph_edges`` -- canonical relational store for typed paper graphs.
* ``coverage_diagnostics`` -- section/figure/table/equation extraction coverage.
* ``paper_analysis_packets`` -- the canonical structured analysis artifact.
* ``paper_review_artifacts`` -- advisory review (only for fully analyzed papers).
* ``evidence_cards`` -- extracted evidence for downstream hypothesis generation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.clock import utcnow
from libs.storage.base import Base


class AnalysisSession(Base):
    """One run of the Phase 2 analysis pipeline against a single paper."""

    __tablename__ = "analysis_sessions"
    __table_args__ = (
        Index("ix_analysis_sessions_cycle_created", "cycle_id", "created_at"),
        Index("ix_analysis_sessions_paper_card", "paper_card_id"),
        Index("ix_analysis_sessions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), default="created")
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    step_log: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    report_artifact_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class IngestedDocument(Base):
    """Persisted full-text artifact: normalized document structure from HTML or PDF.

    Written by the ``analysis_ingest`` operator.  Downstream operators
    (chunking, graph extraction, coverage) read from this rather than
    re-fetching the paper.
    """

    __tablename__ = "ingested_documents"
    __table_args__ = (
        UniqueConstraint("analysis_session_id", name="uq_ingested_documents_session"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    fetch_method: Mapped[str] = mapped_column(String(20))  # "html" or "pdf_docling"
    source_url: Mapped[str] = mapped_column(Text)
    raw_content: Mapped[str] = mapped_column(Text)
    normalized_sections: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    normalized_figures: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    normalized_tables: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    normalized_equations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    quality_assessment: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fetch_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PaperChunk(Base):
    """Structure-aware chunk derived from an ingested document."""

    __tablename__ = "paper_chunks"
    __table_args__ = (
        Index("ix_paper_chunks_session_ordinal", "analysis_session_id", "ordinal"),
        Index("ix_paper_chunks_paper_type", "paper_card_id", "chunk_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    # section | paragraph | figure | table | equation
    chunk_type: Mapped[str] = mapped_column(String(50))
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class GraphNode(Base):
    """Typed graph node in the canonical relational store."""

    __tablename__ = "graph_nodes"
    __table_args__ = (
        Index("ix_graph_nodes_session_type", "analysis_session_id", "node_type"),
        Index("ix_graph_nodes_paper", "paper_card_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    # paper | section | concept | method | experiment | dataset | figure | table | equation
    node_type: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    age_node_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class GraphEdge(Base):
    """Typed relation in the canonical relational store."""

    __tablename__ = "graph_edges"
    __table_args__ = (
        Index("ix_graph_edges_source", "source_node_id"),
        Index("ix_graph_edges_target", "target_node_id"),
        Index("ix_graph_edges_session_type", "analysis_session_id", "edge_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # contained_in | defines | proposes | uses | evaluates | illustrates | compares | depends_on
    edge_type: Mapped[str] = mapped_column(String(50))
    properties: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    age_edge_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class CoverageDiagnostic(Base):
    """Extraction coverage diagnostic for one analysis session."""

    __tablename__ = "coverage_diagnostics"
    __table_args__ = (
        UniqueConstraint("analysis_session_id", name="uq_coverage_diagnostics_session"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_coverage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    figure_coverage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    table_coverage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    equation_coverage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    unlinked_artifacts: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PaperAnalysisPacket(Base):
    """Canonical structured analysis artifact for a fully analyzed paper."""

    __tablename__ = "paper_analysis_packets"
    __table_args__ = (
        UniqueConstraint("analysis_session_id", name="uq_paper_analysis_packets_session"),
        Index("ix_paper_analysis_packets_paper", "paper_card_id"),
        Index("ix_paper_analysis_packets_charter", "charter_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text)
    key_contributions: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    methods_used: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    datasets_referenced: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    reproducibility_notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    graph_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    coverage_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_depth: Mapped[str] = mapped_column(String(20), default="full")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class PaperReviewArtifact(Base):
    """Advisory review artifact linked to a paper analysis packet.

    Only generated for papers that reach full-text analysis.
    Advisory -- never treated as the canonical evidence source.
    """

    __tablename__ = "paper_review_artifacts"
    __table_args__ = (
        Index("ix_paper_review_artifacts_paper", "paper_card_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_packet_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper_analysis_packets.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    strengths: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    weaknesses: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    open_questions: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    critique: Mapped[str | None] = mapped_column(Text, nullable=True)
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reading_priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EvidenceCard(Base):
    """Extracted evidence for downstream hypothesis generation."""

    __tablename__ = "evidence_cards"
    __table_args__ = (
        Index("ix_evidence_cards_charter_type", "charter_id", "evidence_type"),
        Index("ix_evidence_cards_paper", "paper_card_id"),
        Index("ix_evidence_cards_cycle", "cycle_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    charter_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_charters.id", ondelete="CASCADE"),
        nullable=False,
    )
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("paper_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_packet_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("paper_analysis_packets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # finding | method_claim | dataset_availability | limitation | comparison
    evidence_type: Mapped[str] = mapped_column(String(50))
    claim: Mapped[str] = mapped_column(Text)
    supporting_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_chunk_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source_graph_node_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    analysis_depth: Mapped[str] = mapped_column(String(20), default="full")  # "metadata" or "full"
    contradiction_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    redundancy_group: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
