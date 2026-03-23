"""Add output_contract_checks to verification_reports."""

import sqlalchemy as sa
from alembic import op

revision = "20260323_000007"
down_revision = "20260323_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "verification_reports",
        sa.Column("output_contract_checks", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("verification_reports", "output_contract_checks")
