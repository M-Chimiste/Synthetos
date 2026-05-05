"""Runtime model settings catalog and role bindings.

Revision ID: 20260417_000001
Revises: 20260416_000001
Create Date: 2026-04-17 09:00:00.000000
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "20260417_000001"
down_revision = "20260416_000001"
branch_labels = None
depends_on = None

ANTHROPIC_KEY = "anthropic:claude-sonnet-4-20250514"
LOCAL_KEY = "local:default:http://localhost:11434/v1"
ANTHROPIC_ID = uuid.uuid5(uuid.NAMESPACE_URL, ANTHROPIC_KEY)
LOCAL_ID = uuid.uuid5(uuid.NAMESPACE_URL, LOCAL_KEY)


def upgrade() -> None:
    op.create_table(
        "model_catalog_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("provider_type", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=300), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("default_temperature", sa.Float(), nullable=True),
        sa.Column("default_max_tokens", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_error", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "provider_type in ('anthropic', 'openai', 'google', 'openai_compatible')",
            name="ck_model_catalog_entries_provider_type",
        ),
        sa.CheckConstraint(
            "provider_type != 'openai_compatible' or base_url is not null",
            name="ck_model_catalog_entries_openai_compatible_base_url",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_catalog_entries"),
        sa.UniqueConstraint("key", name="uq_model_catalog_entries_key"),
    )
    op.create_index(
        "ix_model_catalog_entries_enabled", "model_catalog_entries", ["enabled"]
    )

    op.create_table(
        "model_role_bindings",
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("catalog_entry_id", sa.Uuid(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["catalog_entry_id"],
            ["model_catalog_entries.id"],
            name="fk_model_role_bindings_catalog_entry_id_model_catalog_entries",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("role", name="pk_model_role_bindings"),
    )

    catalog_table = sa.table(
        "model_catalog_entries",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String),
        sa.column("display_name", sa.String),
        sa.column("provider_type", sa.String),
        sa.column("provider_name", sa.String),
        sa.column("model", sa.String),
        sa.column("base_url", sa.String),
        sa.column("default_temperature", sa.Float),
        sa.column("default_max_tokens", sa.Integer),
        sa.column("enabled", sa.Boolean),
        sa.column("notes", sa.Text),
    )
    op.bulk_insert(
        catalog_table,
        [
            {
                "id": ANTHROPIC_ID,
                "key": ANTHROPIC_KEY,
                "display_name": "Claude Sonnet 4",
                "provider_type": "anthropic",
                "provider_name": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "base_url": None,
                "default_temperature": 0.7,
                "default_max_tokens": 4096,
                "enabled": True,
                "notes": "Seeded from configs/models.yaml.",
            },
            {
                "id": LOCAL_ID,
                "key": LOCAL_KEY,
                "display_name": "Local default",
                "provider_type": "openai_compatible",
                "provider_name": "local",
                "model": "default",
                "base_url": "http://localhost:11434/v1",
                "default_temperature": 0.7,
                "default_max_tokens": 4096,
                "enabled": True,
                "notes": "Seeded from configs/models.yaml local provider.",
            },
        ],
    )

    binding_table = sa.table(
        "model_role_bindings",
        sa.column("role", sa.String),
        sa.column("catalog_entry_id", sa.Uuid()),
        sa.column("temperature", sa.Float),
        sa.column("max_tokens", sa.Integer),
    )
    op.bulk_insert(
        binding_table,
        [
            {
                "role": "planning",
                "catalog_entry_id": ANTHROPIC_ID,
                "temperature": 0.5,
                "max_tokens": None,
            },
            {
                "role": "retrieval_synthesis",
                "catalog_entry_id": ANTHROPIC_ID,
                "temperature": None,
                "max_tokens": None,
            },
            {
                "role": "metadata_analysis",
                "catalog_entry_id": LOCAL_ID,
                "temperature": 0.3,
                "max_tokens": None,
            },
            {
                "role": "coding",
                "catalog_entry_id": LOCAL_ID,
                "temperature": 0.2,
                "max_tokens": None,
            },
            {
                "role": "summarization",
                "catalog_entry_id": LOCAL_ID,
                "temperature": 0.3,
                "max_tokens": None,
            },
            {
                "role": "evaluation",
                "catalog_entry_id": ANTHROPIC_ID,
                "temperature": 0.2,
                "max_tokens": None,
            },
            {
                "role": "report_writing",
                "catalog_entry_id": ANTHROPIC_ID,
                "temperature": 0.5,
                "max_tokens": None,
            },
            {
                "role": "hypothesis_generation",
                "catalog_entry_id": ANTHROPIC_ID,
                "temperature": 0.7,
                "max_tokens": None,
            },
            {
                "role": "protocol_drafting",
                "catalog_entry_id": ANTHROPIC_ID,
                "temperature": 0.3,
                "max_tokens": None,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("model_role_bindings")
    op.drop_index("ix_model_catalog_entries_enabled", table_name="model_catalog_entries")
    op.drop_table("model_catalog_entries")
