"""Phase 2 tables: evidence_cards, hypothesis_cards, experiment_specs."""

import sqlalchemy as sa
from alembic import op

revision = "20260322_000004"
down_revision = "20260322_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_cards",
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
        # Core evidence fields
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("strength", sa.String(length=32), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("relevance_rationale", sa.Text(), nullable=False),
        # Provenance
        sa.Column("source_section", sa.String(length=255), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("read_depth", sa.String(length=32), nullable=False, server_default="abstract"),
        # Conflict and redundancy
        sa.Column("conflict_with", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("redundant_with", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("conflict_notes", sa.Text(), nullable=True),
        # LLM lineage
        sa.Column("model_route_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_id", sa.String(length=255), nullable=False),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_evidence_cards_public_id", "evidence_cards", ["public_id"], unique=True)
    op.create_index("ix_evidence_cards_cycle_id", "evidence_cards", ["cycle_id"])
    op.create_index("ix_evidence_cards_paper_card_id", "evidence_cards", ["paper_card_id"])

    op.create_table(
        "hypothesis_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("research_cycles.id"),
            nullable=False,
        ),
        # Content
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("approach_summary", sa.Text(), nullable=False),
        # Evidence linkage
        sa.Column("supporting_evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("counter_evidence", sa.JSON(), nullable=False, server_default="[]"),
        # Portfolio ranking
        sa.Column("portfolio_rank", sa.Integer(), nullable=True),
        sa.Column("portfolio_score", sa.Float(), nullable=True),
        sa.Column("ranking_rationale", sa.Text(), nullable=True),
        # Status lifecycle
        sa.Column("status", sa.String(length=64), nullable=False, server_default="generated"),
        # Critique
        sa.Column("critique_summary", sa.Text(), nullable=True),
        sa.Column("novelty_score", sa.Float(), nullable=True),
        sa.Column("feasibility_score", sa.Float(), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True),
        sa.Column("critique_issues", sa.JSON(), nullable=False, server_default="[]"),
        # LLM lineage
        sa.Column("model_route_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_id", sa.String(length=255), nullable=False),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_hypothesis_cards_public_id", "hypothesis_cards", ["public_id"], unique=True,
    )
    op.create_index("ix_hypothesis_cards_cycle_id", "hypothesis_cards", ["cycle_id"])
    op.create_index("ix_hypothesis_cards_status", "hypothesis_cards", ["cycle_id", "status"])
    op.create_index("ix_hypothesis_cards_portfolio_rank", "hypothesis_cards", ["portfolio_rank"])

    op.create_table(
        "experiment_specs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("research_cycles.id"),
            nullable=False,
        ),
        sa.Column(
            "hypothesis_card_id",
            sa.Integer(),
            sa.ForeignKey("hypothesis_cards.id"),
            nullable=False,
        ),
        # Protocol definition
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("baseline_description", sa.Text(), nullable=False),
        sa.Column("method_description", sa.Text(), nullable=False),
        # Structured protocol fields
        sa.Column("controls", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("datasets", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("artifacts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("stop_conditions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("expected_outputs", sa.JSON(), nullable=False, server_default="[]"),
        # Validation
        sa.Column("status", sa.String(length=64), nullable=False, server_default="draft"),
        sa.Column("validation_issues", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        # Resource estimates
        sa.Column("estimated_runtime_minutes", sa.Integer(), nullable=True),
        sa.Column("gpu_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resource_requirements", sa.JSON(), nullable=False, server_default="{}"),
        # LLM lineage
        sa.Column("model_route_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_id", sa.String(length=255), nullable=False),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_experiment_specs_public_id", "experiment_specs", ["public_id"], unique=True,
    )
    op.create_index("ix_experiment_specs_cycle_id", "experiment_specs", ["cycle_id"])
    op.create_index(
        "ix_experiment_specs_hypothesis_card_id", "experiment_specs", ["hypothesis_card_id"],
    )
    op.create_index("ix_experiment_specs_status", "experiment_specs", ["cycle_id", "status"])


def downgrade() -> None:
    op.drop_table("experiment_specs")
    op.drop_table("hypothesis_cards")
    op.drop_table("evidence_cards")
