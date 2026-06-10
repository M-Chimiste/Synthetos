"""LLM call transcript table and per-role timeout settings.

Revision ID: 20260609_000002
Revises: 20260609_000001
Create Date: 2026-06-09 09:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260609_000002"
down_revision = "20260609_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("cycle_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=300), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("request_kind", sa.String(length=20), nullable=False),
        sa.Column("response_model", sa.String(length=200), nullable=True),
        sa.Column("messages_hash", sa.String(length=64), nullable=False),
        sa.Column("messages", JSONB, nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("finish_reason", sa.String(length=30), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column(
            "fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt_log", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_llm_calls_job_id_jobs", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name="fk_llm_calls_cycle_id_research_cycles",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_llm_calls"),
    )
    op.create_index("ix_llm_calls_role_created_at", "llm_calls", ["role", "created_at"])
    op.create_index("ix_llm_calls_job_id", "llm_calls", ["job_id"])
    op.create_index("ix_llm_calls_outcome", "llm_calls", ["outcome"])
    op.create_index("ix_llm_calls_cycle_id", "llm_calls", ["cycle_id"])

    op.add_column(
        "model_catalog_entries",
        sa.Column("default_timeout_s", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_role_bindings",
        sa.Column("timeout_s", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_role_bindings", "timeout_s")
    op.drop_column("model_catalog_entries", "default_timeout_s")
    op.drop_index("ix_llm_calls_cycle_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_outcome", table_name="llm_calls")
    op.drop_index("ix_llm_calls_job_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_role_created_at", table_name="llm_calls")
    op.drop_table("llm_calls")
