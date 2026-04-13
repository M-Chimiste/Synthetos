"""Phase 2 analysis pipeline -- ingested documents, analysis sessions, chunks,
graph nodes/edges, coverage diagnostics, analysis packets, review artifacts,
evidence cards.

Revision ID: 20260412_000001
Revises: 20260411_000001
Create Date: 2026-04-12 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "20260412_000001"
down_revision = "20260411_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Conditionally enable Apache AGE (optional -- relational fallback)
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS age;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Apache AGE not available: %. Using relational graph fallback.', SQLERRM;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------
    # Add analysis_status to paper_cards
    # ------------------------------------------------------------------
    op.add_column(
        "paper_cards",
        sa.Column(
            "analysis_status", sa.String(length=50),
            nullable=False, server_default="not_analyzed",
        ),
    )

    # ------------------------------------------------------------------
    # analysis_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "analysis_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("charter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="created"),
        sa.Column("budget", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("step_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report_artifact_path", sa.String(length=1024), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name=op.f("fk_analysis_sessions_cycle_id_research_cycles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name=op.f("fk_analysis_sessions_charter_id_research_charters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_card_id"],
            ["paper_cards.id"],
            name=op.f("fk_analysis_sessions_paper_card_id_paper_cards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_sessions")),
    )
    op.create_index(
        "ix_analysis_sessions_cycle_created",
        "analysis_sessions",
        ["cycle_id", "created_at"],
    )
    op.create_index(
        "ix_analysis_sessions_paper_card",
        "analysis_sessions",
        ["paper_card_id"],
    )
    op.create_index(
        "ix_analysis_sessions_status",
        "analysis_sessions",
        ["status"],
    )

    # ------------------------------------------------------------------
    # ingested_documents
    # ------------------------------------------------------------------
    op.create_table(
        "ingested_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fetch_method", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("normalized_sections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("normalized_figures", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("normalized_tables", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("normalized_equations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quality_assessment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetch_duration_ms", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_session_id"],
            ["analysis_sessions.id"],
            name=op.f("fk_ingested_documents_analysis_session_id_analysis_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_card_id"],
            ["paper_cards.id"],
            name=op.f("fk_ingested_documents_paper_card_id_paper_cards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingested_documents")),
        sa.UniqueConstraint("analysis_session_id", name="uq_ingested_documents_session"),
    )

    # ------------------------------------------------------------------
    # paper_chunks
    # ------------------------------------------------------------------
    op.create_table(
        "paper_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_type", sa.String(length=50), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_session_id"],
            ["analysis_sessions.id"],
            name=op.f("fk_paper_chunks_analysis_session_id_analysis_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_card_id"],
            ["paper_cards.id"],
            name=op.f("fk_paper_chunks_paper_card_id_paper_cards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_chunks")),
    )
    op.create_index(
        "ix_paper_chunks_session_ordinal",
        "paper_chunks",
        ["analysis_session_id", "ordinal"],
    )
    op.create_index(
        "ix_paper_chunks_paper_type",
        "paper_chunks",
        ["paper_card_id", "chunk_type"],
    )
    op.execute(
        "CREATE INDEX ix_paper_chunks_embedding ON paper_chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ------------------------------------------------------------------
    # graph_nodes
    # ------------------------------------------------------------------
    op.create_table(
        "graph_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_type", sa.String(length=50), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("age_node_id", sa.String(length=100), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_session_id"],
            ["analysis_sessions.id"],
            name=op.f("fk_graph_nodes_analysis_session_id_analysis_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_card_id"],
            ["paper_cards.id"],
            name=op.f("fk_graph_nodes_paper_card_id_paper_cards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_nodes")),
    )
    op.create_index(
        "ix_graph_nodes_session_type",
        "graph_nodes",
        ["analysis_session_id", "node_type"],
    )
    op.create_index(
        "ix_graph_nodes_paper",
        "graph_nodes",
        ["paper_card_id"],
    )

    # ------------------------------------------------------------------
    # graph_edges
    # ------------------------------------------------------------------
    op.create_table(
        "graph_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("edge_type", sa.String(length=50), nullable=False),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("age_edge_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_session_id"],
            ["analysis_sessions.id"],
            name=op.f("fk_graph_edges_analysis_session_id_analysis_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_edges_source_node_id_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_edges_target_node_id_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_edges")),
    )
    op.create_index("ix_graph_edges_source", "graph_edges", ["source_node_id"])
    op.create_index("ix_graph_edges_target", "graph_edges", ["target_node_id"])
    op.create_index(
        "ix_graph_edges_session_type",
        "graph_edges",
        ["analysis_session_id", "edge_type"],
    )

    # ------------------------------------------------------------------
    # coverage_diagnostics
    # ------------------------------------------------------------------
    op.create_table(
        "coverage_diagnostics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("figure_coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("table_coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("equation_coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("unlinked_artifacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_session_id"],
            ["analysis_sessions.id"],
            name=op.f("fk_coverage_diagnostics_analysis_session_id_analysis_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coverage_diagnostics")),
        sa.UniqueConstraint("analysis_session_id", name="uq_coverage_diagnostics_session"),
    )

    # ------------------------------------------------------------------
    # paper_analysis_packets
    # ------------------------------------------------------------------
    op.create_table(
        "paper_analysis_packets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("charter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_contributions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("methods_used", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("datasets_referenced", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reproducibility_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("graph_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("coverage_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("analysis_depth", sa.String(length=20), nullable=False, server_default="full"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_session_id"],
            ["analysis_sessions.id"],
            name=op.f("fk_paper_analysis_packets_analysis_session_id_analysis_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_card_id"],
            ["paper_cards.id"],
            name=op.f("fk_paper_analysis_packets_paper_card_id_paper_cards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name=op.f("fk_paper_analysis_packets_charter_id_research_charters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_analysis_packets")),
        sa.UniqueConstraint("analysis_session_id", name="uq_paper_analysis_packets_session"),
    )
    op.create_index(
        "ix_paper_analysis_packets_paper",
        "paper_analysis_packets",
        ["paper_card_id"],
    )
    op.create_index(
        "ix_paper_analysis_packets_charter",
        "paper_analysis_packets",
        ["charter_id"],
    )

    # ------------------------------------------------------------------
    # paper_review_artifacts
    # ------------------------------------------------------------------
    op.create_table(
        "paper_review_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_packet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strengths", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("weaknesses", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("open_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("critique", sa.Text(), nullable=True),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reading_priority", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_packet_id"],
            ["paper_analysis_packets.id"],
            name=op.f("fk_paper_review_artifacts_analysis_packet_id_paper_analysis_packets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_card_id"],
            ["paper_cards.id"],
            name=op.f("fk_paper_review_artifacts_paper_card_id_paper_cards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_review_artifacts")),
    )
    op.create_index(
        "ix_paper_review_artifacts_paper",
        "paper_review_artifacts",
        ["paper_card_id"],
    )

    # ------------------------------------------------------------------
    # evidence_cards
    # ------------------------------------------------------------------
    op.create_table(
        "evidence_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("charter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_packet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("supporting_text", sa.Text(), nullable=True),
        sa.Column("source_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_graph_node_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("analysis_depth", sa.String(length=20), nullable=False, server_default="full"),
        sa.Column("contradiction_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("redundancy_group", sa.String(length=100), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name=op.f("fk_evidence_cards_charter_id_research_charters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name=op.f("fk_evidence_cards_cycle_id_research_cycles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_card_id"],
            ["paper_cards.id"],
            name=op.f("fk_evidence_cards_paper_card_id_paper_cards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_packet_id"],
            ["paper_analysis_packets.id"],
            name=op.f("fk_evidence_cards_analysis_packet_id_paper_analysis_packets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_cards")),
    )
    op.create_index(
        "ix_evidence_cards_charter_type",
        "evidence_cards",
        ["charter_id", "evidence_type"],
    )
    op.create_index(
        "ix_evidence_cards_paper",
        "evidence_cards",
        ["paper_card_id"],
    )
    op.create_index(
        "ix_evidence_cards_cycle",
        "evidence_cards",
        ["cycle_id"],
    )
    op.execute(
        "CREATE INDEX ix_evidence_cards_embedding ON evidence_cards "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_evidence_cards_embedding")
    op.drop_index("ix_evidence_cards_cycle", table_name="evidence_cards")
    op.drop_index("ix_evidence_cards_paper", table_name="evidence_cards")
    op.drop_index("ix_evidence_cards_charter_type", table_name="evidence_cards")
    op.drop_table("evidence_cards")

    op.drop_index("ix_paper_review_artifacts_paper", table_name="paper_review_artifacts")
    op.drop_table("paper_review_artifacts")

    op.drop_index("ix_paper_analysis_packets_charter", table_name="paper_analysis_packets")
    op.drop_index("ix_paper_analysis_packets_paper", table_name="paper_analysis_packets")
    op.drop_table("paper_analysis_packets")

    op.drop_table("coverage_diagnostics")

    op.drop_index("ix_graph_edges_session_type", table_name="graph_edges")
    op.drop_index("ix_graph_edges_target", table_name="graph_edges")
    op.drop_index("ix_graph_edges_source", table_name="graph_edges")
    op.drop_table("graph_edges")

    op.drop_index("ix_graph_nodes_paper", table_name="graph_nodes")
    op.drop_index("ix_graph_nodes_session_type", table_name="graph_nodes")
    op.drop_table("graph_nodes")

    op.execute("DROP INDEX IF EXISTS ix_paper_chunks_embedding")
    op.drop_index("ix_paper_chunks_paper_type", table_name="paper_chunks")
    op.drop_index("ix_paper_chunks_session_ordinal", table_name="paper_chunks")
    op.drop_table("paper_chunks")

    op.drop_table("ingested_documents")

    op.drop_index("ix_analysis_sessions_status", table_name="analysis_sessions")
    op.drop_index("ix_analysis_sessions_paper_card", table_name="analysis_sessions")
    op.drop_index("ix_analysis_sessions_cycle_created", table_name="analysis_sessions")
    op.drop_table("analysis_sessions")

    op.drop_column("paper_cards", "analysis_status")
