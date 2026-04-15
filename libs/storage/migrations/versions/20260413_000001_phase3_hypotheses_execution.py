"""Phase 3 hypotheses, protocols, execution, and verification.

Revision ID: 20260413_000001
Revises: 20260412_000001
Create Date: 2026-04-13 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260413_000001"
down_revision = "20260412_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # hypothesis_sessions
    # ------------------------------------------------------------------
    op.create_table(
        "hypothesis_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="created"),
        sa.Column("budget", JSONB(), nullable=True),
        sa.Column("stats", JSONB(), nullable=True),
        sa.Column("step_log", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["charter_id"], ["research_charters.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["research_cycles.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hypothesis_sessions_cycle_created",
        "hypothesis_sessions",
        ["cycle_id", "created_at"],
    )
    op.create_index(
        "ix_hypothesis_sessions_status",
        "hypothesis_sessions",
        ["status"],
    )

    # ------------------------------------------------------------------
    # hypothesis_cards
    # ------------------------------------------------------------------
    op.create_table(
        "hypothesis_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hypothesis_session_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=True),
        sa.Column(
            "supporting_evidence_ids",
            JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("critique", JSONB(), nullable=True),
        sa.Column("novelty_score", sa.Float(), nullable=True),
        sa.Column("feasibility_score", sa.Float(), nullable=True),
        sa.Column("impact_score", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="candidate"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["hypothesis_session_id"], ["hypothesis_sessions.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"], ["research_charters.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["research_cycles.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hypothesis_cards_session", "hypothesis_cards", ["hypothesis_session_id"],
    )
    op.create_index(
        "ix_hypothesis_cards_charter_status", "hypothesis_cards", ["charter_id", "status"],
    )
    op.create_index(
        "ix_hypothesis_cards_cycle", "hypothesis_cards", ["cycle_id"],
    )

    # ------------------------------------------------------------------
    # experiment_specs
    # ------------------------------------------------------------------
    op.create_table(
        "experiment_specs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hypothesis_card_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("baseline", JSONB(), nullable=False),
        sa.Column(
            "controls",
            JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "metrics",
            JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "expected_artifacts",
            JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "stop_conditions",
            JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("code_plan", JSONB(), nullable=True),
        sa.Column("hardware_profile", JSONB(), nullable=True),
        sa.Column("base_image", sa.String(length=500), nullable=True),
        sa.Column("build_recipe", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["hypothesis_card_id"], ["hypothesis_cards.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"], ["research_charters.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["research_cycles.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_specs_hypothesis", "experiment_specs", ["hypothesis_card_id"],
    )
    op.create_index(
        "ix_experiment_specs_cycle_status", "experiment_specs", ["cycle_id", "status"],
    )

    # ------------------------------------------------------------------
    # run_records
    # ------------------------------------------------------------------
    op.create_table(
        "run_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_spec_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("workspace_path", sa.String(length=1024), nullable=True),
        sa.Column("container_id", sa.String(length=100), nullable=True),
        sa.Column("image_ref", sa.String(length=500), nullable=True),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("env_vars", JSONB(), nullable=True),
        sa.Column("resource_limits", JSONB(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_path", sa.String(length=1024), nullable=True),
        sa.Column("stderr_path", sa.String(length=1024), nullable=True),
        sa.Column("metrics_output", JSONB(), nullable=True),
        sa.Column("artifact_manifest", JSONB(), nullable=True),
        sa.Column("resource_usage", JSONB(), nullable=True),
        sa.Column("failure_class", sa.String(length=50), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_spec_id"], ["experiment_specs.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"], ["research_charters.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["research_cycles.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_run_records_spec", "run_records", ["experiment_spec_id"],
    )
    op.create_index(
        "ix_run_records_cycle_status", "run_records", ["cycle_id", "status"],
    )
    op.create_index(
        "ix_run_records_container", "run_records", ["container_id"],
    )

    # ------------------------------------------------------------------
    # run_telemetry
    # ------------------------------------------------------------------
    op.create_table(
        "run_telemetry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_record_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_record_id"], ["run_records.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_run_telemetry_run_ts", "run_telemetry", ["run_record_id", "timestamp"],
    )

    # ------------------------------------------------------------------
    # verification_reports
    # ------------------------------------------------------------------
    op.create_table(
        "verification_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_record_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.String(length=50), nullable=False),
        sa.Column("baseline_comparison", JSONB(), nullable=True),
        sa.Column("artifact_checks", JSONB(), nullable=True),
        sa.Column("output_contract", JSONB(), nullable=True),
        sa.Column("metric_sanity", JSONB(), nullable=True),
        sa.Column("warnings", JSONB(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_record_id"], ["run_records.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"], ["research_charters.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["research_cycles.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_verification_reports_run", "verification_reports", ["run_record_id"],
    )
    op.create_index(
        "ix_verification_reports_cycle_verdict",
        "verification_reports",
        ["cycle_id", "verdict"],
    )

    # ------------------------------------------------------------------
    # failure_postmortems
    # ------------------------------------------------------------------
    op.create_table(
        "failure_postmortems",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_record_id", sa.Uuid(), nullable=False),
        sa.Column("verification_report_id", sa.Uuid(), nullable=True),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("failure_class", sa.String(length=50), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("contributing_factors", JSONB(), nullable=True),
        sa.Column("error_trace", sa.Text(), nullable=True),
        sa.Column("next_step_recommendation", sa.Text(), nullable=True),
        sa.Column("lessons", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_record_id"], ["run_records.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verification_report_id"],
            ["verification_reports.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"], ["research_charters.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], ["research_cycles.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_failure_postmortems_run", "failure_postmortems", ["run_record_id"],
    )
    op.create_index(
        "ix_failure_postmortems_cycle", "failure_postmortems", ["cycle_id"],
    )


def downgrade() -> None:
    op.drop_table("failure_postmortems")
    op.drop_table("verification_reports")
    op.drop_table("run_telemetry")
    op.drop_table("run_records")
    op.drop_table("experiment_specs")
    op.drop_table("hypothesis_cards")
    op.drop_table("hypothesis_sessions")
