"""Phase 4 remediation, directional signal, frontier tracking, and recommendations.

Revision ID: 20260414_000001
Revises: 20260413_000001
Create Date: 2026-04-14 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260414_000001"
down_revision = "20260413_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Column additions to existing tables
    # ------------------------------------------------------------------

    # run_records.parent_run_id (self-referential FK for retry lineage)
    op.add_column(
        "run_records",
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_run_records_parent_run_id_run_records",
        "run_records",
        "run_records",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_run_records_parent", "run_records", ["parent_run_id"])

    # experiment_specs.primary_metric_index
    op.add_column(
        "experiment_specs",
        sa.Column("primary_metric_index", sa.Integer(), nullable=True, server_default="0"),
    )

    # ------------------------------------------------------------------
    # remediation_actions
    # ------------------------------------------------------------------
    op.create_table(
        "remediation_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_record_id", sa.Uuid(), nullable=False),
        sa.Column("retry_run_id", sa.Uuid(), nullable=True),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("experiment_spec_id", sa.Uuid(), nullable=False),
        sa.Column("failure_class", sa.String(length=50), nullable=False),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("strategy_tier", sa.String(length=20), nullable=False),
        sa.Column("action_detail", JSONB(), nullable=True),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_remediation_actions"),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_records.id"],
            name="fk_remediation_actions_run_record_id_run_records",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["retry_run_id"],
            ["run_records.id"],
            name="fk_remediation_actions_retry_run_id_run_records",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name="fk_remediation_actions_charter_id_research_charters",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name="fk_remediation_actions_cycle_id_research_cycles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_spec_id"],
            ["experiment_specs.id"],
            name="fk_remediation_actions_experiment_spec_id_experiment_specs",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_remediation_actions_run", "remediation_actions", ["run_record_id"]
    )
    op.create_index(
        "ix_remediation_actions_cycle_spec",
        "remediation_actions",
        ["cycle_id", "experiment_spec_id"],
    )
    op.create_index(
        "ix_remediation_actions_retry", "remediation_actions", ["retry_run_id"]
    )

    # ------------------------------------------------------------------
    # directional_signals
    # ------------------------------------------------------------------
    op.create_table(
        "directional_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_record_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("experiment_spec_id", sa.Uuid(), nullable=False),
        sa.Column("signal", sa.String(length=50), nullable=False),
        sa.Column("primary_metric_name", sa.String(length=200), nullable=False),
        sa.Column("primary_metric_value", sa.Float(), nullable=False),
        sa.Column("primary_metric_delta", sa.Float(), nullable=True),
        sa.Column("primary_metric_direction", sa.String(length=20), nullable=False),
        sa.Column("constraint_metrics", JSONB(), nullable=True),
        sa.Column("history_window", JSONB(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_directional_signals"),
        sa.UniqueConstraint("run_record_id", name="uq_directional_signals_run"),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_records.id"],
            name="fk_directional_signals_run_record_id_run_records",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name="fk_directional_signals_charter_id_research_charters",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name="fk_directional_signals_cycle_id_research_cycles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_spec_id"],
            ["experiment_specs.id"],
            name="fk_directional_signals_experiment_spec_id_experiment_specs",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_directional_signals_run", "directional_signals", ["run_record_id"]
    )
    op.create_index(
        "ix_directional_signals_spec_created",
        "directional_signals",
        ["experiment_spec_id", "created_at"],
    )
    op.create_index(
        "ix_directional_signals_cycle", "directional_signals", ["cycle_id"]
    )

    # ------------------------------------------------------------------
    # metric_frontiers
    # ------------------------------------------------------------------
    op.create_table(
        "metric_frontiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("hypothesis_card_id", sa.Uuid(), nullable=False),
        sa.Column("primary_metric_name", sa.String(length=200), nullable=False),
        sa.Column("primary_metric_direction", sa.String(length=20), nullable=False),
        sa.Column("best_run_id", sa.Uuid(), nullable=False),
        sa.Column("best_experiment_spec_id", sa.Uuid(), nullable=False),
        sa.Column("best_metric_value", sa.Float(), nullable=False),
        sa.Column("best_achieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_since_improvement", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_metric_frontiers"),
        sa.UniqueConstraint(
            "charter_id", "hypothesis_card_id", name="uq_metric_frontiers_line"
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name="fk_metric_frontiers_charter_id_research_charters",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_card_id"],
            ["hypothesis_cards.id"],
            name="fk_metric_frontiers_hypothesis_card_id_hypothesis_cards",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["best_run_id"],
            ["run_records.id"],
            name="fk_metric_frontiers_best_run_id_run_records",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["best_experiment_spec_id"],
            ["experiment_specs.id"],
            name="fk_metric_frontiers_best_experiment_spec_id_experiment_specs",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_metric_frontiers_best_run", "metric_frontiers", ["best_run_id"]
    )

    # ------------------------------------------------------------------
    # run_recommendations
    # ------------------------------------------------------------------
    op.create_table(
        "run_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_record_id", sa.Uuid(), nullable=False),
        sa.Column("charter_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("experiment_spec_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_type", sa.String(length=50), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("inputs_summary", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_run_recommendations"),
        sa.UniqueConstraint("run_record_id", name="uq_run_recommendations_run"),
        sa.ForeignKeyConstraint(
            ["run_record_id"],
            ["run_records.id"],
            name="fk_run_recommendations_run_record_id_run_records",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["charter_id"],
            ["research_charters.id"],
            name="fk_run_recommendations_charter_id_research_charters",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"],
            ["research_cycles.id"],
            name="fk_run_recommendations_cycle_id_research_cycles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_spec_id"],
            ["experiment_specs.id"],
            name="fk_run_recommendations_experiment_spec_id_experiment_specs",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_run_recommendations_run", "run_recommendations", ["run_record_id"]
    )
    op.create_index(
        "ix_run_recommendations_cycle", "run_recommendations", ["cycle_id"]
    )

    # ------------------------------------------------------------------
    # verification_reports FK columns (must come after target tables exist)
    # ------------------------------------------------------------------
    op.add_column(
        "verification_reports",
        sa.Column("directional_signal_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "verification_reports",
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_verification_reports_directional_signal_directional_signals",
        "verification_reports",
        "directional_signals",
        ["directional_signal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_verification_reports_recommendation_id_run_recommendations",
        "verification_reports",
        "run_recommendations",
        ["recommendation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Drop FK columns from verification_reports
    op.drop_constraint(
        "fk_verification_reports_recommendation_id_run_recommendations",
        "verification_reports",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_verification_reports_directional_signal_id_directional_signals",
        "verification_reports",
        type_="foreignkey",
    )
    op.drop_column("verification_reports", "recommendation_id")
    op.drop_column("verification_reports", "directional_signal_id")

    # Drop new tables (reverse order of creation)
    op.drop_table("run_recommendations")
    op.drop_table("metric_frontiers")
    op.drop_table("directional_signals")
    op.drop_table("remediation_actions")

    # Drop column additions to existing tables
    op.drop_column("experiment_specs", "primary_metric_index")
    op.drop_index("ix_run_records_parent", table_name="run_records")
    op.drop_constraint(
        "fk_run_records_parent_run_id_run_records",
        "run_records",
        type_="foreignkey",
    )
    op.drop_column("run_records", "parent_run_id")
