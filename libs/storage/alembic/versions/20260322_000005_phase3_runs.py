"""Phase 3 tables: run_records and run_telemetry_events."""

import sqlalchemy as sa
from alembic import op

revision = "20260322_000005"
down_revision = "20260322_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=False),
        sa.Column(
            "experiment_spec_id",
            sa.Integer(),
            sa.ForeignKey("experiment_specs.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("execution_profile", sa.String(length=64), nullable=False),
        sa.Column("workspace_path", sa.String(length=512), nullable=False),
        sa.Column("artifact_root", sa.String(length=512), nullable=False),
        sa.Column("stdout_path", sa.String(length=512), nullable=True),
        sa.Column("stderr_path", sa.String(length=512), nullable=True),
        sa.Column("patch_archive_path", sa.String(length=512), nullable=True),
        sa.Column("base_commit", sa.String(length=128), nullable=True),
        sa.Column("base_branch", sa.String(length=255), nullable=True),
        sa.Column("image", sa.String(length=255), nullable=False),
        sa.Column("build_recipe", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("command", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("env_vars", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("mounts", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("hardware_profile", sa.String(length=64), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=False),
        sa.Column("cpu_limit", sa.String(length=64), nullable=True),
        sa.Column("gpu_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("network_mode", sa.String(length=32), nullable=False, server_default="disabled"),
        sa.Column("bound_skill_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("prompt_lineage", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("model_lineage", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("latest_resource_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metrics_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("artifact_manifest", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("failure_classification", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_run_records_public_id", "run_records", ["public_id"], unique=True)
    op.create_index("ix_run_records_cycle_id", "run_records", ["cycle_id"])
    op.create_index("ix_run_records_experiment_spec_id", "run_records", ["experiment_spec_id"])
    op.create_index("ix_run_records_status", "run_records", ["status"])

    op.create_table(
        "run_telemetry_events",
        sa.Column("sequence_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column(
            "run_record_id",
            sa.Integer(),
            sa.ForeignKey("run_records.id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("stream", sa.String(length=32), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_run_telemetry_events_public_id", "run_telemetry_events", ["public_id"], unique=True
    )
    op.create_index("ix_run_telemetry_events_run_record_id", "run_telemetry_events", ["run_record_id"])

    op.add_column(
        "skill_execution_records",
        sa.Column("run_record_id", sa.Integer(), sa.ForeignKey("run_records.id"), nullable=True),
    )
    op.create_index(
        "ix_skill_execution_records_run_record_id",
        "skill_execution_records",
        ["run_record_id"],
    )

    op.add_column(
        "model_invocations",
        sa.Column("run_record_id", sa.Integer(), sa.ForeignKey("run_records.id"), nullable=True),
    )
    op.create_index("ix_model_invocations_run_record_id", "model_invocations", ["run_record_id"])


def downgrade() -> None:
    op.drop_index("ix_model_invocations_run_record_id", table_name="model_invocations")
    op.drop_column("model_invocations", "run_record_id")
    op.drop_index(
        "ix_skill_execution_records_run_record_id",
        table_name="skill_execution_records",
    )
    op.drop_column("skill_execution_records", "run_record_id")
    op.drop_table("run_telemetry_events")
    op.drop_table("run_records")
