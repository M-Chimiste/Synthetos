"""Phase C: budget tracking and autonomy mode columns on research_cycles."""

import sqlalchemy as sa
from alembic import op

revision = "20260324_000014"
down_revision = "20260324_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Budget limits (user-defined)
    op.add_column(
        "research_cycles",
        sa.Column("budget_max_compute_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "research_cycles",
        sa.Column("budget_max_total_runs", sa.Integer(), nullable=True),
    )
    op.add_column(
        "research_cycles",
        sa.Column("budget_max_wall_clock_hours", sa.Float(), nullable=True),
    )
    op.add_column(
        "research_cycles",
        sa.Column(
            "budget_max_runs_per_hypothesis", sa.Integer(), nullable=True,
        ),
    )

    # Budget tracking (system-maintained)
    op.add_column(
        "research_cycles",
        sa.Column(
            "budget_used_compute_minutes",
            sa.Float(),
            server_default="0.0",
            nullable=False,
        ),
    )
    op.add_column(
        "research_cycles",
        sa.Column(
            "budget_used_run_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "research_cycles",
        sa.Column(
            "budget_runs_per_hypothesis",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
    )

    # Autonomy mode
    op.add_column(
        "research_cycles",
        sa.Column(
            "autonomy_mode",
            sa.String(32),
            server_default="supervised",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("research_cycles", "autonomy_mode")
    op.drop_column("research_cycles", "budget_runs_per_hypothesis")
    op.drop_column("research_cycles", "budget_used_run_count")
    op.drop_column("research_cycles", "budget_used_compute_minutes")
    op.drop_column("research_cycles", "budget_max_runs_per_hypothesis")
    op.drop_column("research_cycles", "budget_max_wall_clock_hours")
    op.drop_column("research_cycles", "budget_max_total_runs")
    op.drop_column("research_cycles", "budget_max_compute_minutes")
