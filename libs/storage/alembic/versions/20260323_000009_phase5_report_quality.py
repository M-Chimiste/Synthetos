"""Add quality_metadata to report_bundles."""

import sqlalchemy as sa
from alembic import op

revision = "20260323_000009"
down_revision = "20260323_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_bundles",
        sa.Column("quality_metadata", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("report_bundles", "quality_metadata")
