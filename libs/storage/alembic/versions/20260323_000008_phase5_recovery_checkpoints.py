"""Add recovery checkpoint columns to research_cycles."""

import sqlalchemy as sa
from alembic import op

revision = "20260323_000008"
down_revision = "20260323_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_cycles",
        sa.Column("last_completed_operator", sa.String(128), nullable=True),
    )
    op.add_column(
        "research_cycles",
        sa.Column("last_completed_job_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "research_cycles",
        sa.Column("resume_payload", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("research_cycles", "resume_payload")
    op.drop_column("research_cycles", "last_completed_job_id")
    op.drop_column("research_cycles", "last_completed_operator")
