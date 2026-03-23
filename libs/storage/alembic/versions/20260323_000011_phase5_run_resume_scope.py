"""Add run-scoped checkpoint columns for resume recovery."""

import sqlalchemy as sa
from alembic import op

revision = "20260323_000011"
down_revision = "20260323_000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "run_records",
        sa.Column("last_completed_operator", sa.String(128), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("last_completed_job_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "run_records",
        sa.Column("resume_payload", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("run_records", "resume_payload")
    op.drop_column("run_records", "last_completed_job_id")
    op.drop_column("run_records", "last_completed_operator")
