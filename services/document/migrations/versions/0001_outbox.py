"""outbox

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(op.f("ix_outbox_event_type"), "outbox", ["event_type"], unique=False)
    op.create_index(op.f("ix_outbox_published_at"), "outbox", ["published_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_outbox_published_at"), table_name="outbox")
    op.drop_index(op.f("ix_outbox_event_type"), table_name="outbox")
    op.drop_table("outbox")
