"""PayWay Purchase (hosted checkout): khqr_payments.kind + payment_option; invoice payment method PAYWAY

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-13 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "method IN ('cash', 'card', 'ABA', 'KHQR', 'credit', 'deposit')"
NEW = "method IN ('cash', 'card', 'ABA', 'KHQR', 'PAYWAY', 'credit', 'deposit')"


def upgrade() -> None:
    with op.batch_alter_table("khqr_payments") as t:
        t.add_column(sa.Column("kind", sa.String(length=10), server_default="khqr", nullable=False))
        t.add_column(sa.Column("payment_option", sa.String(length=20), nullable=True))
        t.create_check_constraint("ck_khqr_payments_kind", "kind IN ('khqr', 'checkout')")
    with op.batch_alter_table("invoice_payments") as t:
        t.drop_constraint("ck_invoice_payments_method", type_="check")
        t.create_check_constraint("ck_invoice_payments_method", NEW)


def downgrade() -> None:
    with op.batch_alter_table("invoice_payments") as t:
        t.drop_constraint("ck_invoice_payments_method", type_="check")
        t.create_check_constraint("ck_invoice_payments_method", OLD)
    with op.batch_alter_table("khqr_payments") as t:
        t.drop_constraint("ck_khqr_payments_kind", type_="check")
        t.drop_column("payment_option")
        t.drop_column("kind")
