"""Add model_invocations table for LLM call tracking."""

import sqlalchemy as sa
from alembic import op

revision = "20260322_000002"
down_revision = "20260322_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_invocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("research_cycles.id"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id"),
            nullable=True,
        ),
        sa.Column("route_id", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_id", sa.String(length=255), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_model_invocations_public_id", "model_invocations", ["public_id"], unique=True)
    op.create_index("ix_model_invocations_cycle_id", "model_invocations", ["cycle_id"])
    op.create_index("ix_model_invocations_job_id", "model_invocations", ["job_id"])


def downgrade() -> None:
    op.drop_table("model_invocations")
