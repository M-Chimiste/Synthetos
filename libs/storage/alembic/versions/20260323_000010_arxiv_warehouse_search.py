"""Add canonical arXiv warehouse and sync tables."""

import sqlalchemy as sa
from alembic import op

revision = "20260323_000010"
down_revision = "20260323_000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "arxiv_papers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("arxiv_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("categories", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=False),
        sa.Column("pdf_url", sa.String(length=512), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("raw_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("embedding_model_id", sa.String(length=255), nullable=True),
        sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_arxiv_papers_public_id", "arxiv_papers", ["public_id"], unique=True)
    op.create_index("ix_arxiv_papers_arxiv_id", "arxiv_papers", ["arxiv_id"], unique=True)
    op.create_index("ix_arxiv_papers_content_hash", "arxiv_papers", ["content_hash"])

    op.create_table(
        "arxiv_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("requested_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_updated_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inserted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reembedded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_arxiv_sync_runs_public_id", "arxiv_sync_runs", ["public_id"], unique=True)
    op.create_index("ix_arxiv_sync_runs_status", "arxiv_sync_runs", ["status"])
    op.create_index("ix_arxiv_sync_runs_mode", "arxiv_sync_runs", ["mode"])
    op.create_index("ix_arxiv_sync_runs_source", "arxiv_sync_runs", ["source"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE arxiv_papers ALTER COLUMN embedding TYPE vector(768) USING embedding::vector")
        op.execute(
            """
            CREATE INDEX ix_arxiv_papers_search_text_tsv
            ON arxiv_papers
            USING GIN (to_tsvector('english', search_text))
            """
        )
        op.execute(
            """
            CREATE INDEX ix_arxiv_papers_embedding_hnsw
            ON arxiv_papers
            USING hnsw (embedding vector_cosine_ops)
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_arxiv_papers_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS ix_arxiv_papers_search_text_tsv")
    op.drop_table("arxiv_sync_runs")
    op.drop_table("arxiv_papers")
