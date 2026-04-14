"""Phase 6 canonical pattern memory, approvals, and periodic job state.

Revision ID: 20260416_000001
Revises: 20260415_000001
Create Date: 2026-04-16 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "20260416_000001"
down_revision = "20260415_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # jobs.reclaim_count (Phase 6 §5.1 stale-job reclaim)
    # ------------------------------------------------------------------
    op.add_column(
        "jobs",
        sa.Column(
            "reclaim_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # ------------------------------------------------------------------
    # canonical_patterns
    # ------------------------------------------------------------------
    op.create_table(
        "canonical_patterns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pattern_type", sa.String(length=50), nullable=False),
        sa.Column("content_key", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("structured_body", JSONB(), nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "trust_tier", sa.String(length=20), nullable=False, server_default="auto"
        ),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reinforced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("staleness_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "source_charter_ids",
            ARRAY(PGUUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "consolidation_version", sa.Integer(), nullable=False, server_default="1"
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_canonical_patterns"),
        sa.UniqueConstraint(
            "pattern_type", "content_key", name="uq_canonical_patterns_type_key"
        ),
    )
    op.create_index(
        "ix_canonical_patterns_type", "canonical_patterns", ["pattern_type"]
    )
    op.create_index(
        "ix_canonical_patterns_trust", "canonical_patterns", ["trust_tier"]
    )
    op.create_index(
        "ix_canonical_patterns_last_reinforced",
        "canonical_patterns",
        ["last_reinforced_at"],
    )
    # HNSW index for cosine similarity over 768-dim embedding
    op.execute(
        "CREATE INDEX ix_canonical_patterns_embedding ON canonical_patterns "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ------------------------------------------------------------------
    # pattern_observations
    # ------------------------------------------------------------------
    op.create_table(
        "pattern_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pattern_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("source_artifact_type", sa.String(length=50), nullable=False),
        sa.Column("source_artifact_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("contribution", JSONB(), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pattern_observations"),
        sa.ForeignKeyConstraint(
            ["pattern_id"],
            ["canonical_patterns.id"],
            name="fk_pattern_observations_pattern_id_canonical_patterns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name="fk_pattern_observations_charter_id_research_charters",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name="fk_pattern_observations_cycle_id_research_cycles",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "pattern_id",
            "source_artifact_type",
            "source_artifact_id",
            name="uq_pattern_observations_artifact",
        ),
    )
    op.create_index(
        "ix_pattern_observations_pattern", "pattern_observations", ["pattern_id"]
    )
    op.create_index(
        "ix_pattern_observations_cycle", "pattern_observations", ["cycle_id"]
    )
    op.create_index(
        "ix_pattern_observations_charter", "pattern_observations", ["charter_id"]
    )

    # ------------------------------------------------------------------
    # pattern_approvals
    # ------------------------------------------------------------------
    op.create_table(
        "pattern_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pattern_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column(
            "actor_type", sa.String(length=50), nullable=False, server_default="user"
        ),
        sa.Column("actor_id", sa.String(length=200), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pattern_approvals"),
        sa.ForeignKeyConstraint(
            ["pattern_id"],
            ["canonical_patterns.id"],
            name="fk_pattern_approvals_pattern_id_canonical_patterns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name="fk_pattern_approvals_charter_id_research_charters",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_pattern_approvals_pattern", "pattern_approvals", ["pattern_id"]
    )
    op.create_index(
        "ix_pattern_approvals_charter", "pattern_approvals", ["charter_id"]
    )

    # ------------------------------------------------------------------
    # periodic_job_state
    # ------------------------------------------------------------------
    op.create_table(
        "periodic_job_state",
        sa.Column("job_kind", sa.String(length=64), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("job_kind", name="pk_periodic_job_state"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "reclaim_count")
    op.drop_table("periodic_job_state")
    op.drop_index("ix_pattern_approvals_charter", table_name="pattern_approvals")
    op.drop_index("ix_pattern_approvals_pattern", table_name="pattern_approvals")
    op.drop_table("pattern_approvals")
    op.drop_index("ix_pattern_observations_charter", table_name="pattern_observations")
    op.drop_index("ix_pattern_observations_cycle", table_name="pattern_observations")
    op.drop_index("ix_pattern_observations_pattern", table_name="pattern_observations")
    op.drop_table("pattern_observations")
    op.execute("DROP INDEX IF EXISTS ix_canonical_patterns_embedding")
    op.drop_index(
        "ix_canonical_patterns_last_reinforced", table_name="canonical_patterns"
    )
    op.drop_index("ix_canonical_patterns_trust", table_name="canonical_patterns")
    op.drop_index("ix_canonical_patterns_type", table_name="canonical_patterns")
    op.drop_table("canonical_patterns")
