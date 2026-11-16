"""T2: discount approvals on Telegram

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discount_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("seller_role", sa.String(length=40), nullable=False),
        sa.Column("cart_hash", sa.String(length=64), nullable=False),
        sa.Column("worst_pct", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("cap_pct", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("discount_usd", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total_usd", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("needs_owner", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'used')", name="ck_discount_approvals_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discount_approvals_branch_id", "discount_approvals", ["branch_id"])


def downgrade() -> None:
    op.drop_index("ix_discount_approvals_branch_id", table_name="discount_approvals")
    op.drop_table("discount_approvals")
