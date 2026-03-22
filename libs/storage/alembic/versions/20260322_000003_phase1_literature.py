"""Phase 1 literature triage tables: source_retrieval_sessions, paper_cards, screening_decisions."""

import sqlalchemy as sa
from alembic import op

revision = "20260322_000003"
down_revision = "20260322_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_retrieval_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("research_cycles.id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("query_params", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="pending"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_source_retrieval_sessions_public_id",
        "source_retrieval_sessions",
        ["public_id"],
        unique=True,
    )
    op.create_index(
        "ix_source_retrieval_sessions_cycle_id",
        "source_retrieval_sessions",
        ["cycle_id"],
    )

    op.create_table(
        "paper_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("research_cycles.id"),
            nullable=False,
        ),
        sa.Column(
            "retrieval_session_id",
            sa.Integer(),
            sa.ForeignKey("source_retrieval_sessions.id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("categories", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("publication_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("pdf_url", sa.String(length=512), nullable=True),
        sa.Column("metadata_extra", sa.JSON(), nullable=False, server_default="{}"),
        # Lifecycle
        sa.Column(
            "lifecycle_status",
            sa.String(length=64),
            nullable=False,
            server_default="retrieved",
        ),
        # Triage
        sa.Column("triage_score", sa.Float(), nullable=True),
        sa.Column("triage_rationale", sa.Text(), nullable=True),
        sa.Column("triage_model_route", sa.String(length=128), nullable=True),
        # Shortlist
        sa.Column("shortlist_rank", sa.Integer(), nullable=True),
        sa.Column("shortlist_reason", sa.Text(), nullable=True),
        # Escalation
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("escalation_type", sa.String(length=32), nullable=True),
        sa.Column("fulltext_artifact_path", sa.String(length=512), nullable=True),
        # Dedup
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("cycle_id", "content_hash", name="uq_paper_card_dedup"),
    )
    op.create_index("ix_paper_cards_public_id", "paper_cards", ["public_id"], unique=True)
    op.create_index("ix_paper_cards_cycle_id", "paper_cards", ["cycle_id"])
    op.create_index("ix_paper_cards_retrieval_session_id", "paper_cards", ["retrieval_session_id"])
    op.create_index("ix_paper_cards_lifecycle_status", "paper_cards", ["cycle_id", "lifecycle_status"])
    op.create_index("ix_paper_cards_content_hash", "paper_cards", ["content_hash"])

    op.create_table(
        "screening_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("research_cycles.id"),
            nullable=False,
        ),
        sa.Column(
            "paper_card_id",
            sa.Integer(),
            sa.ForeignKey("paper_cards.id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("model_route_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_id", sa.String(length=255), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_screening_decisions_public_id",
        "screening_decisions",
        ["public_id"],
        unique=True,
    )
    op.create_index("ix_screening_decisions_cycle_id", "screening_decisions", ["cycle_id"])
    op.create_index("ix_screening_decisions_paper_card_id", "screening_decisions", ["paper_card_id"])
    op.create_index(
        "ix_screening_decisions_cycle_decision",
        "screening_decisions",
        ["cycle_id", "decision"],
    )


def downgrade() -> None:
    op.drop_table("screening_decisions")
    op.drop_table("paper_cards")
    op.drop_table("source_retrieval_sessions")
