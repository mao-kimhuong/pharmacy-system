"""T2: refill reminder days and opening hours per branch

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("branch_settings", sa.Column("refill_reminder_days", sa.Integer(), server_default="3",
                                               nullable=False))  # fmt: skip
    op.add_column("branch_settings", sa.Column("opening_hours", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("branch_settings", "opening_hours")
    op.drop_column("branch_settings", "refill_reminder_days")
