"""Phase 5 autonomy budgets and loop decisions.

Revision ID: 20260415_000001
Revises: 20260414_000001
Create Date: 2026-04-15 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260415_000001"
down_revision = "20260414_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # autonomy_budgets
    # ------------------------------------------------------------------
    op.create_table(
        "autonomy_budgets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "cycle_id",
            sa.Uuid(),
            sa.ForeignKey("research_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "wall_clock_elapsed_s", sa.Float(), nullable=False, server_default="0.0"
        ),
        sa.Column("runs_per_hypothesis", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_run_completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("cycle_id", name="uq_autonomy_budgets_cycle"),
    )

    # ------------------------------------------------------------------
    # loop_decisions
    # ------------------------------------------------------------------
    op.create_table(
        "loop_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "cycle_id",
            sa.Uuid(),
            sa.ForeignKey("research_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "charter_id",
            sa.Uuid(),
            sa.ForeignKey("research_charters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_record_id",
            sa.Uuid(),
            sa.ForeignKey("run_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recommendation_id",
            sa.Uuid(),
            sa.ForeignKey("run_recommendations.id", ondelete="SET NULL"),
            nullable=False,
        ),
        sa.Column("iteration_number", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("gate_triggered", sa.String(100), nullable=True),
        sa.Column("budget_snapshot", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "hypothesis_card_id",
            sa.Uuid(),
            sa.ForeignKey("hypothesis_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "next_hypothesis_card_id",
            sa.Uuid(),
            sa.ForeignKey("hypothesis_cards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("next_action", sa.String(50), nullable=True),
        sa.Column("context_summary_path", sa.String(1024), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_loop_decisions_cycle", "loop_decisions", ["cycle_id"])
    op.create_index("ix_loop_decisions_run", "loop_decisions", ["run_record_id"])


def downgrade() -> None:
    op.drop_table("loop_decisions")
    op.drop_table("autonomy_budgets")
