"""T2: structured dose on Rx items (refill reminders)

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rx_items", sa.Column("units_per_dose", sa.Numeric(precision=8, scale=2), nullable=True))
    op.add_column("rx_items", sa.Column("doses_per_day", sa.Numeric(precision=5, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column("rx_items", "doses_per_day")
    op.drop_column("rx_items", "units_per_dose")
