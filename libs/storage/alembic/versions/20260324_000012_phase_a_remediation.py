"""Add remediation_actions table and run_records remediation columns."""

import sqlalchemy as sa
from alembic import op

revision = "20260324_000012"
down_revision = "20260323_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "remediation_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column(
            "cycle_id",
            sa.Integer(),
            sa.ForeignKey("research_cycles.id"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "run_record_id",
            sa.Integer(),
            sa.ForeignKey("run_records.id"),
            index=True,
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("failure_classification", sa.String(64), nullable=False),
        sa.Column("prompt_mode", sa.String(32), nullable=False),
        sa.Column("prompt_id", sa.String(255), nullable=False),
        sa.Column("model_route_id", sa.String(128), nullable=False),
        sa.Column("diagnosis", sa.Text(), nullable=False),
        sa.Column("fix_type", sa.String(64), nullable=False),
        sa.Column("fix_description", sa.Text(), nullable=False),
        sa.Column("fix_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("prior_attempts_summary", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("outcome", sa.String(32), index=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "run_records",
        sa.Column("remediation_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "run_records",
        sa.Column("is_remediated_run", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("run_records", "is_remediated_run")
    op.drop_column("run_records", "remediation_count")
    op.drop_table("remediation_actions")
