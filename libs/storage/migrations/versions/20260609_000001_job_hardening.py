"""Job hardening: retry attempts, backoff gate, cancel flag, error detail.

Revision ID: 20260609_000001
Revises: 20260418_000001
Create Date: 2026-06-09 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260609_000001"
down_revision = "20260418_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "jobs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column("jobs", sa.Column("not_before", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("error_detail", JSONB, nullable=True))
    op.add_column(
        "jobs",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("jobs", "cancel_requested")
    op.drop_column("jobs", "error_detail")
    op.drop_column("jobs", "started_at")
    op.drop_column("jobs", "not_before")
    op.drop_column("jobs", "max_attempts")
    op.drop_column("jobs", "attempt_count")
