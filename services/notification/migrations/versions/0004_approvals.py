"""T2 phase 2: approvals on Telegram, value limit

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
    op.add_column("alert_settings", sa.Column("telegram_approval_max_usd", sa.Numeric(precision=14, scale=2),
                                              server_default="100", nullable=False))  # fmt: skip
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("value_usd", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("controlled", sa.Boolean(), nullable=False),
        sa.Column("needs_pin", sa.Boolean(), nullable=False),
        sa.Column("needs_owner", sa.Boolean(), nullable=False),
        sa.Column("telegram_ok", sa.Boolean(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_name", sa.String(length=160), nullable=False),
        sa.Column("decided_via", sa.String(length=10), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_approvals_ref", "approvals", ["kind", "ref_id"], unique=True)
    op.create_index("ix_approvals_branch_id", "approvals", ["branch_id"])


def downgrade() -> None:
    op.drop_index("ix_approvals_branch_id", table_name="approvals")
    op.drop_index("uq_approvals_ref", table_name="approvals")
    op.drop_table("approvals")
    op.drop_column("alert_settings", "telegram_approval_max_usd")
