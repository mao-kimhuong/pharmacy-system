"""T2: the supplier confirmed a PO on Telegram

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("supplier_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("purchase_orders", sa.Column("supplier_confirmed_by", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "supplier_confirmed_by")
    op.drop_column("purchase_orders", "supplier_confirmed_at")
