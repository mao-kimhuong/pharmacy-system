"""invoice_payments.reference (bank transfer / card terminal); khqr_payments.provider_status (declined)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-14 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoice_payments", sa.Column("reference", sa.String(length=40), nullable=True))
    op.add_column("khqr_payments", sa.Column("provider_status", sa.String(length=12), nullable=True))


def downgrade() -> None:
    op.drop_column("khqr_payments", "provider_status")
    op.drop_column("invoice_payments", "reference")
