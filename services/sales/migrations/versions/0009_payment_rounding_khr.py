"""invoices.payment_rounding_khr: riel due (rounded) − exact riel when riel paid the sale exactly

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-13 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("payment_rounding_khr", sa.Numeric(precision=12, scale=2), server_default="0",
                                        nullable=False))  # fmt: skip


def downgrade() -> None:
    op.drop_column("invoices", "payment_rounding_khr")
