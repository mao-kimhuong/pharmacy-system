"""T2: customer language and credit terms (Telegram reminders), clinic groups

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("preferred_lang", sa.String(length=2), server_default="km", nullable=False))
    op.add_column("customers", sa.Column("credit_terms_days", sa.Integer(), server_default="30", nullable=False))
    op.add_column("customer_groups", sa.Column("is_clinic", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("customer_groups", "is_clinic")
    op.drop_column("customers", "credit_terms_days")
    op.drop_column("customers", "preferred_lang")
