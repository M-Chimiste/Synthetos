"""Phase B: metric_frontiers table, directional signal columns on verification_reports, writeup columns on report_bundles."""

import sqlalchemy as sa
from alembic import op

revision = "20260324_000013"
down_revision = "20260324_000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create metric_frontiers table
    op.create_table(
        "metric_frontiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column(
            "hypothesis_card_id",
            sa.Integer(),
            sa.ForeignKey("hypothesis_cards.id"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "charter_id",
            sa.Integer(),
            sa.ForeignKey("research_charters.id"),
            index=True,
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("best_value", sa.Float(), nullable=False),
        sa.Column("best_run_public_id", sa.String(64), nullable=False),
        sa.Column(
            "best_run_id",
            sa.Integer(),
            sa.ForeignKey("run_records.id"),
            nullable=False,
        ),
        sa.Column("runs_since_improvement", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "last_updated_run_id",
            sa.Integer(),
            sa.ForeignKey("run_records.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "hypothesis_card_id", "metric_name", name="uq_frontier_hypothesis_metric"
        ),
    )

    # 2. Add directional signal columns to verification_reports
    op.add_column(
        "verification_reports",
        sa.Column("directional_signal", sa.String(32), nullable=True),
    )
    op.add_column(
        "verification_reports",
        sa.Column("directional_signal_detail", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "verification_reports",
        sa.Column("self_critic_result", sa.JSON(), server_default="{}", nullable=False),
    )
    op.create_index(
        "ix_verification_reports_directional_signal",
        "verification_reports",
        ["directional_signal"],
    )

    # 3. Add writeup linkage columns to report_bundles
    op.add_column(
        "report_bundles",
        sa.Column(
            "run_record_id",
            sa.Integer(),
            sa.ForeignKey("run_records.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "report_bundles",
        sa.Column(
            "hypothesis_card_id",
            sa.Integer(),
            sa.ForeignKey("hypothesis_cards.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_report_bundles_run_record_id", "report_bundles", ["run_record_id"])
    op.create_index(
        "ix_report_bundles_hypothesis_card_id", "report_bundles", ["hypothesis_card_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_report_bundles_hypothesis_card_id", table_name="report_bundles")
    op.drop_index("ix_report_bundles_run_record_id", table_name="report_bundles")
    op.drop_column("report_bundles", "hypothesis_card_id")
    op.drop_column("report_bundles", "run_record_id")
    op.drop_index("ix_verification_reports_directional_signal", table_name="verification_reports")
    op.drop_column("verification_reports", "self_critic_result")
    op.drop_column("verification_reports", "directional_signal_detail")
    op.drop_column("verification_reports", "directional_signal")
    op.drop_table("metric_frontiers")
