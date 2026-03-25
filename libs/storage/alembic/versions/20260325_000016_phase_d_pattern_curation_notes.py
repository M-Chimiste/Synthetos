"""Phase D: add curation notes to canonical patterns."""

import sqlalchemy as sa
from alembic import op

revision = "20260325_000016"
down_revision = "20260324_000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "canonical_patterns",
        sa.Column("curation_notes", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("canonical_patterns", "curation_notes")
