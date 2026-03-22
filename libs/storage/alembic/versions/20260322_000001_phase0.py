"""Phase 0 foundation schema."""

import sqlalchemy as sa
from alembic import op

revision = "20260322_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "research_charters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=False),
        sa.Column("success_criteria", sa.JSON(), nullable=False),
        sa.Column("budget_envelope", sa.JSON(), nullable=False),
        sa.Column("source_scope", sa.JSON(), nullable=False),
        sa.Column("stop_conditions", sa.JSON(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "research_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("charter_id", sa.Integer(), sa.ForeignKey("research_charters.id"), nullable=False),
        sa.Column("current_state_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("current_status", sa.String(length=64), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "research_state_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("transition_reason", sa.String(length=255), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("scope_used", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_foreign_key(
        "fk_research_cycles_current_state_snapshot",
        "research_cycles",
        "research_state_snapshots",
        ["current_state_snapshot_id"],
        ["id"],
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=True),
        sa.Column("operator_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_by", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "domain_events",
        sa.Column("sequence_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("scope_used", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "report_bundles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("report_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("artifact_path", sa.String(length=512), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "approval_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "skill_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("skill_key", sa.String(length=255), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("skill_key"),
    )
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("definition_id", sa.Integer(), sa.ForeignKey("skill_definitions.id"), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("hooks_path", sa.String(length=512), nullable=True),
        sa.Column("hook_exports", sa.JSON(), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("definition_id", "version", name="uq_skill_version"),
    )
    op.create_table(
        "skill_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=False),
        sa.Column("skill_version_id", sa.Integer(), sa.ForeignKey("skill_versions.id"), nullable=False),
        sa.Column("operator_name", sa.String(length=128), nullable=False),
        sa.Column("binding_reason", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "skill_execution_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("skill_binding_id", sa.Integer(), sa.ForeignKey("skill_bindings.id"), nullable=False),
        sa.Column("operator_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "skill_validation_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("skill_definition_id", sa.Integer(), sa.ForeignKey("skill_definitions.id"), nullable=True),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )
    op.create_table(
        "orchestrator_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "orchestrator_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("orchestrator_clients.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_table(
        "orchestrator_commands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("orchestrator_clients.id"), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("research_cycles.id"), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("scope_used", sa.String(length=128), nullable=True),
        sa.Column("command_name", sa.String(length=128), nullable=False),
        sa.Column("target_resource", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_id"),
    )


def downgrade() -> None:
    for table in [
        "orchestrator_commands",
        "orchestrator_tokens",
        "orchestrator_clients",
        "skill_validation_issues",
        "skill_execution_records",
        "skill_bindings",
        "skill_versions",
        "skill_definitions",
        "approval_events",
        "report_bundles",
        "domain_events",
        "jobs",
        "research_cycles",
        "research_state_snapshots",
        "research_charters",
    ]:
        op.drop_table(table)

