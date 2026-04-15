"""Initial Phase 0 schema.

Revision ID: 20260410_000001
Revises:
Create Date: 2026-04-10 08:15:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260410_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orchestrator_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orchestrator_clients")),
    )

    op.create_table(
        "research_charters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=False),
        sa.Column("source_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_charters")),
    )

    op.create_table(
        "api_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["orchestrator_clients.id"],
            name=op.f("fk_api_tokens_client_id_orchestrator_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
    )

    op.create_table(
        "research_cycles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("charter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name=op.f("fk_research_cycles_charter_id_research_charters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_cycles")),
    )

    op.create_table(
        "domain_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("charter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name=op.f("fk_domain_events_charter_id_research_charters"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name=op.f("fk_domain_events_cycle_id_research_cycles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_events")),
    )
    op.create_index(
        "ix_domain_events_charter_created",
        "domain_events",
        ["charter_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_domain_events_created",
        "domain_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_domain_events_cycle_created",
        "domain_events",
        ["cycle_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_domain_events_type", "domain_events", ["event_type"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("claimed_by", sa.String(length=200), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name=op.f("fk_jobs_cycle_id_research_cycles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "priority", "created_at"], unique=False)

    op.create_table(
        "model_call_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("prompt_template_id", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name=op.f("fk_model_call_records_cycle_id_research_cycles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_model_call_records_job_id_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_call_records")),
    )

    op.create_table(
        "skill_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("phase", sa.String(length=100), nullable=True),
        sa.Column("trust_tier", sa.String(length=50), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source_path", sa.String(length=500), nullable=True),
        sa.Column("discovered_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_definitions")),
        sa.UniqueConstraint("skill_id", name=op.f("uq_skill_definitions_skill_id")),
    )

    op.create_table(
        "skill_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_def_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operator_type", sa.String(length=100), nullable=True),
        sa.Column("bound_at", sa.DateTime(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name=op.f("fk_skill_bindings_cycle_id_research_cycles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["skill_def_id"],
            ["skill_definitions.id"],
            name=op.f("fk_skill_bindings_skill_def_id_skill_definitions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_bindings")),
    )


def downgrade() -> None:
    op.drop_table("skill_bindings")
    op.drop_table("skill_definitions")
    op.drop_table("model_call_records")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_domain_events_type", table_name="domain_events")
    op.drop_index("ix_domain_events_cycle_created", table_name="domain_events")
    op.drop_index("ix_domain_events_created", table_name="domain_events")
    op.drop_index("ix_domain_events_charter_created", table_name="domain_events")
    op.drop_table("domain_events")
    op.drop_table("research_cycles")
    op.drop_table("api_tokens")
    op.drop_table("research_charters")
    op.drop_table("orchestrator_clients")
