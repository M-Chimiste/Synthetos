"""Goal-oriented research mode.

Revision ID: 20260418_000001
Revises: 20260417_000001
Create Date: 2026-04-18 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260418_000001"
down_revision = "20260417_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "charter_id",
            sa.Uuid(),
            sa.ForeignKey("research_charters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("goal_statement", sa.Text(), nullable=False),
        sa.Column("success_criteria", JSONB, nullable=False, server_default="[]"),
        sa.Column("policy", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(50), nullable=False, server_default="created"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("report_path", sa.String(1024), nullable=True),
        sa.Column("report_json_path", sa.String(1024), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_research_goals_charter_status",
        "research_goals",
        ["charter_id", "status"],
    )

    op.create_table(
        "goal_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "goal_id",
            sa.Uuid(),
            sa.ForeignKey("research_goals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "charter_id",
            sa.Uuid(),
            sa.ForeignKey("research_charters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cycle_id",
            sa.Uuid(),
            sa.ForeignKey("research_cycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="running"),
        sa.Column("evaluation", JSONB, nullable=True),
        sa.Column("report_path", sa.String(1024), nullable=True),
        sa.Column("report_json_path", sa.String(1024), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("goal_id", "attempt_number", name="uq_goal_attempts_number"),
        sa.UniqueConstraint("cycle_id", name="uq_goal_attempts_cycle"),
    )
    op.create_index("ix_goal_attempts_goal", "goal_attempts", ["goal_id"])
    op.create_index("ix_goal_attempts_cycle", "goal_attempts", ["cycle_id"])


def downgrade() -> None:
    op.drop_index("ix_goal_attempts_cycle", table_name="goal_attempts")
    op.drop_index("ix_goal_attempts_goal", table_name="goal_attempts")
    op.drop_table("goal_attempts")
    op.drop_index("ix_research_goals_charter_status", table_name="research_goals")
    op.drop_table("research_goals")
