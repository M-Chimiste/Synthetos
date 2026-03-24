"""Phase D: canonical patterns and consolidation runs for cross-charter procedural memory."""

import sqlalchemy as sa
from alembic import op

revision = "20260324_000015"
down_revision = "20260324_000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("pattern_type", sa.String(32), index=True, nullable=False),
        sa.Column("polarity", sa.String(16), index=True, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(256), index=True, server_default=""),
        sa.Column("trigger_conditions", sa.JSON(), server_default="[]"),
        sa.Column("proven_actions", sa.JSON(), server_default="[]"),
        sa.Column("disproven_actions", sa.JSON(), server_default="[]"),
        sa.Column("evidence_refs", sa.JSON(), server_default="[]"),
        sa.Column("evidence_count", sa.Integer(), server_default="0"),
        sa.Column("confidence_score", sa.Float(), index=True, server_default="1.0"),
        sa.Column("staleness_context", sa.JSON(), server_default="{}"),
        sa.Column("status", sa.String(32), index=True, server_default="'active'"),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_text", sa.Text(), server_default=""),
        sa.Column("embedding_model_id", sa.String(255), nullable=True),
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # pgvector embedding column — added via raw SQL since Alembic doesn't
    # natively handle custom vector types.
    op.execute("ALTER TABLE canonical_patterns ADD COLUMN embedding vector(768)")

    # Full-text search index on search_text
    op.execute(
        "CREATE INDEX ix_canonical_patterns_search_fts "
        "ON canonical_patterns USING gin (to_tsvector('english', search_text))"
    )

    # Vector similarity index (HNSW for approximate nearest-neighbor)
    op.execute(
        "CREATE INDEX ix_canonical_patterns_embedding_hnsw "
        "ON canonical_patterns USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "pattern_consolidation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("status", sa.String(32), index=True, server_default="'running'"),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("postmortems_scanned", sa.Integer(), server_default="0"),
        sa.Column("runs_scanned", sa.Integer(), server_default="0"),
        sa.Column("patterns_created", sa.Integer(), server_default="0"),
        sa.Column("patterns_updated", sa.Integer(), server_default="0"),
        sa.Column("patterns_decayed", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("pattern_consolidation_runs")
    op.execute("DROP INDEX IF EXISTS ix_canonical_patterns_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_canonical_patterns_search_fts")
    op.drop_table("canonical_patterns")
