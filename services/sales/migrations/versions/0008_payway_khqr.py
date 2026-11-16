"""ABA PayWay KHQR: provider + tran_id, cancel, review, refunds, daily reconciliation

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-12 21:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "status IN ('pending', 'paid', 'expired', 'used', 'needs_refund')"
NEW = "status IN ('pending', 'paid', 'expired', 'cancelled', 'used', 'review', 'needs_refund', 'refunded')"


def upgrade() -> None:
    with op.batch_alter_table("khqr_payments") as t:
        t.add_column(sa.Column("provider", sa.String(length=8), server_default="fake", nullable=False))
        t.add_column(sa.Column("tran_id", sa.String(length=20), nullable=True))
        t.add_column(sa.Column("deeplink", sa.Text(), nullable=True))
        t.add_column(sa.Column("paid_currency", sa.String(length=3), nullable=True))
        t.add_column(sa.Column("review_reason", sa.Text(), nullable=True))
        t.add_column(sa.Column("refunded_amount", sa.Numeric(precision=16, scale=2), server_default="0", nullable=False))
        t.add_column(sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True))
        t.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        t.add_column(sa.Column("cancelled_by", sa.Uuid(), nullable=True))
        t.create_unique_constraint("uq_khqr_payments_tran_id", ["tran_id"])
        t.drop_constraint("ck_khqr_payments_status", type_="check")
        t.create_check_constraint("ck_khqr_payments_status", NEW)
        t.create_check_constraint("ck_khqr_payments_provider", "provider IN ('fake', 'bakong', 'payway')")
    with op.batch_alter_table("sale_returns") as t:
        t.drop_constraint("ck_returns_refund", type_="check")
        t.create_check_constraint("ck_returns_refund", "refund_method IN ('cash', 'credit_note', 'khqr')")
    op.create_table(
        "khqr_refunds",
        sa.Column("khqr_id", sa.Uuid(), sa.ForeignKey("khqr_payments.id"), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=True),
        sa.Column("last_error", sa.String(length=40), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("khqr_id", "source_ref", name="uq_khqr_refunds_source"),
        sa.CheckConstraint("status IN ('due', 'requested', 'refunded')", name="ck_khqr_refunds_status"),
        sa.CheckConstraint("source IN ('failed_sale', 'invoice_cancel', 'return', 'late_payment', 'review')",
                           name="ck_khqr_refunds_source"),
        sa.CheckConstraint("amount > 0", name="ck_khqr_refunds_amount"),
    )
    op.create_index("ix_khqr_refunds_khqr_id", "khqr_refunds", ["khqr_id"])
    op.create_index("ix_khqr_refunds_open", "khqr_refunds", ["branch_id", "status"])
    op.create_table(
        "khqr_reconcile_issues",
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("khqr_id", sa.Uuid(), sa.ForeignKey("khqr_payments.id"), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("ours", sa.JSON(), nullable=False),
        sa.Column("theirs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_date", "khqr_id", "kind", name="uq_khqr_reconcile_issue"),
    )
    op.create_index("ix_khqr_reconcile_issues_run_date", "khqr_reconcile_issues", ["run_date"])
    op.create_index("ix_khqr_reconcile_issues_branch_id", "khqr_reconcile_issues", ["branch_id"])


def downgrade() -> None:
    op.drop_table("khqr_reconcile_issues")
    op.drop_table("khqr_refunds")
    with op.batch_alter_table("sale_returns") as t:
        t.drop_constraint("ck_returns_refund", type_="check")
        t.create_check_constraint("ck_returns_refund", "refund_method IN ('cash', 'credit_note')")
    op.execute("UPDATE khqr_payments SET status = 'needs_refund' WHERE status IN ('review', 'refunded')")
    op.execute("UPDATE khqr_payments SET status = 'expired' WHERE status = 'cancelled'")
    with op.batch_alter_table("khqr_payments") as t:
        t.drop_constraint("ck_khqr_payments_provider", type_="check")
        t.drop_constraint("ck_khqr_payments_status", type_="check")
        t.create_check_constraint("ck_khqr_payments_status", OLD)
        t.drop_constraint("uq_khqr_payments_tran_id", type_="unique")
        for col in ("cancelled_by", "cancelled_at", "checked_at", "refunded_amount", "review_reason", "paid_currency",
                    "deeplink", "tran_id", "provider"):
            t.drop_column(col)
