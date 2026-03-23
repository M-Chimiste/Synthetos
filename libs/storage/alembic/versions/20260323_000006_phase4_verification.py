"""Phase 4 tables: verification_reports and failure_postmortems."""

import sqlalchemy as sa
from alembic import op

revision = "20260323_000006"
down_revision = "20260322_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "verification_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=False),
        sa.Column(
            "run_record_id",
            sa.Integer(),
            sa.ForeignKey("run_records.id"),
            nullable=False,
        ),
        sa.Column(
            "experiment_spec_id",
            sa.Integer(),
            sa.ForeignKey("experiment_specs.id"),
            nullable=False,
        ),
        sa.Column(
            "hypothesis_card_id",
            sa.Integer(),
            sa.ForeignKey("hypothesis_cards.id"),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("outcome_rationale", sa.Text(), nullable=False),
        sa.Column("baseline_comparison", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("historical_comparisons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metric_sanity_checks", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("artifact_checks", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("leakage_signals", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("split_validation", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rerun_note", sa.Text(), nullable=True),
        sa.Column("reviewer_summary", sa.Text(), nullable=False),
        sa.Column("model_route_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_verification_reports_public_id", "verification_reports", ["public_id"], unique=True)
    op.create_index("ix_verification_reports_cycle_id", "verification_reports", ["cycle_id"])
    op.create_index("ix_verification_reports_run_record_id", "verification_reports", ["run_record_id"])
    op.create_index("ix_verification_reports_experiment_spec_id", "verification_reports", ["experiment_spec_id"])
    op.create_index("ix_verification_reports_hypothesis_card_id", "verification_reports", ["hypothesis_card_id"])
    op.create_index("ix_verification_reports_outcome", "verification_reports", ["outcome"])

    op.create_table(
        "failure_postmortems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=False),
        sa.Column(
            "run_record_id",
            sa.Integer(),
            sa.ForeignKey("run_records.id"),
            nullable=False,
        ),
        sa.Column(
            "verification_report_id",
            sa.Integer(),
            sa.ForeignKey("verification_reports.id"),
            nullable=True,
        ),
        sa.Column("failure_class", sa.String(length=64), nullable=False),
        sa.Column("failure_stage", sa.String(length=64), nullable=False),
        sa.Column("root_cause_summary", sa.Text(), nullable=False),
        sa.Column("contributing_factors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("remediation_suggestions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("retrieval_hints", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("protocol_update_hints", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("similar_prior_failures", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("model_route_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_failure_postmortems_public_id", "failure_postmortems", ["public_id"], unique=True)
    op.create_index("ix_failure_postmortems_cycle_id", "failure_postmortems", ["cycle_id"])
    op.create_index("ix_failure_postmortems_run_record_id", "failure_postmortems", ["run_record_id"])
    op.create_index("ix_failure_postmortems_verification_report_id", "failure_postmortems", ["verification_report_id"])
    op.create_index("ix_failure_postmortems_failure_class", "failure_postmortems", ["failure_class"])

    op.add_column(
        "run_records",
        sa.Column("verification_outcome", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_run_records_verification_outcome", "run_records", ["verification_outcome"])


def downgrade() -> None:
    op.drop_index("ix_run_records_verification_outcome", table_name="run_records")
    op.drop_column("run_records", "verification_outcome")
    op.drop_table("failure_postmortems")
    op.drop_table("verification_reports")
