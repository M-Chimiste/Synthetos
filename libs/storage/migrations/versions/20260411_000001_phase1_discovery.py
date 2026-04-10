"""Phase 1 discovery schema -- arxiv corpus, problem profiles, discovery sessions, paper cards.

Revision ID: 20260411_000001
Revises: 20260410_000001
Create Date: 2026-04-11 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "20260411_000001"
down_revision = "20260410_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # arxiv_corpus -- system-wide pre-embedded mirror
    # ------------------------------------------------------------------
    op.create_table(
        "arxiv_corpus",
        sa.Column("arxiv_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("authors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_date", sa.String(length=64), nullable=True),
        sa.Column("updated_date", sa.String(length=64), nullable=True),
        sa.Column("doi", sa.String(length=256), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("pdf_url", sa.String(length=512), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("embedding_model_id", sa.String(length=200), nullable=True),
        sa.Column("embedding_updated_at", sa.String(length=64), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("arxiv_id", name=op.f("pk_arxiv_corpus")),
    )

    # GIN index for full-text search over the generated tsvector
    op.execute("CREATE INDEX ix_arxiv_corpus_tsv ON arxiv_corpus USING gin (tsv)")
    # HNSW index for cosine similarity over the 768-dim embedding
    # m=16, ef_construction=64 -- a sensible default for a few-million-row corpus.
    op.execute(
        "CREATE INDEX ix_arxiv_corpus_embedding ON arxiv_corpus "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.create_index(
        "ix_arxiv_corpus_doi",
        "arxiv_corpus",
        ["doi"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # corpus_import_runs
    # ------------------------------------------------------------------
    op.create_table(
        "corpus_import_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_line", sa.Integer(), nullable=False),
        sa.Column("last_arxiv_id", sa.String(length=64), nullable=True),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corpus_import_runs")),
    )
    op.create_index(
        "ix_corpus_import_runs_source_started",
        "corpus_import_runs",
        ["source_path", "started_at"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # problem_profiles
    # ------------------------------------------------------------------
    op.create_table(
        "problem_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("source_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("view_preference", sa.String(length=32), nullable=False),
        sa.Column("rerank_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("budget", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name=op.f("fk_problem_profiles_cycle_id_research_cycles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_problem_profiles")),
    )
    op.create_index(
        "ix_problem_profiles_cycle",
        "problem_profiles",
        ["cycle_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # discovery_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "discovery_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("charter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("view", sa.String(length=32), nullable=False),
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
            name=op.f("fk_discovery_sessions_cycle_id_research_cycles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name=op.f("fk_discovery_sessions_charter_id_research_charters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["problem_profiles.id"],
            name=op.f("fk_discovery_sessions_profile_id_problem_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_sessions")),
    )
    op.create_index(
        "ix_discovery_sessions_cycle_created",
        "discovery_sessions",
        ["cycle_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_sessions_status",
        "discovery_sessions",
        ["status"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # paper_cards
    # ------------------------------------------------------------------
    op.create_table(
        "paper_cards",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("charter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("authors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("categories", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("venue", sa.String(length=256), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("doi", sa.String(length=256), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("pdf_url", sa.String(length=1024), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("bm25_score", sa.Float(), nullable=True),
        sa.Column("dense_score", sa.Float(), nullable=True),
        sa.Column("first_stage_score", sa.Float(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("view_membership", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("triage_status", sa.String(length=50), nullable=False),
        sa.Column("triage_reason", sa.Text(), nullable=True),
        sa.Column("metadata_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["discovery_sessions.id"],
            name=op.f("fk_paper_cards_session_id_discovery_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name=op.f("fk_paper_cards_charter_id_research_charters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_cards")),
        sa.UniqueConstraint(
            "session_id",
            "dedupe_key",
            name="uq_paper_cards_session_dedupe",
        ),
    )
    op.create_index(
        "ix_paper_cards_session_score",
        "paper_cards",
        ["session_id", "final_score"],
        unique=False,
    )
    op.create_index(
        "ix_paper_cards_charter_created",
        "paper_cards",
        ["charter_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_paper_cards_session_status",
        "paper_cards",
        ["session_id", "triage_status"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # discovery_evaluations
    # ------------------------------------------------------------------
    op.create_table(
        "discovery_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric", sa.String(length=50), nullable=False),
        sa.Column("k", sa.Integer(), nullable=True),
        sa.Column("value", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["discovery_sessions.id"],
            name=op.f("fk_discovery_evaluations_session_id_discovery_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_evaluations")),
    )
    op.create_index(
        "ix_discovery_evaluations_session",
        "discovery_evaluations",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_discovery_evaluations_session", table_name="discovery_evaluations")
    op.drop_table("discovery_evaluations")

    op.drop_index("ix_corpus_import_runs_source_started", table_name="corpus_import_runs")
    op.drop_table("corpus_import_runs")

    op.drop_index("ix_paper_cards_session_status", table_name="paper_cards")
    op.drop_index("ix_paper_cards_charter_created", table_name="paper_cards")
    op.drop_index("ix_paper_cards_session_score", table_name="paper_cards")
    op.drop_table("paper_cards")

    op.drop_index("ix_discovery_sessions_status", table_name="discovery_sessions")
    op.drop_index("ix_discovery_sessions_cycle_created", table_name="discovery_sessions")
    op.drop_table("discovery_sessions")

    op.drop_index("ix_problem_profiles_cycle", table_name="problem_profiles")
    op.drop_table("problem_profiles")

    op.drop_index("ix_arxiv_corpus_doi", table_name="arxiv_corpus")
    op.execute("DROP INDEX IF EXISTS ix_arxiv_corpus_embedding")
    op.execute("DROP INDEX IF EXISTS ix_arxiv_corpus_tsv")
    op.drop_table("arxiv_corpus")
