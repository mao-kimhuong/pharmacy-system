"""T2 phase 1: chat roles, links, link tokens, customer consent, refill reminders, campaigns

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("messages", "target", type_=sa.String(length=60))
    op.add_column("messages", sa.Column("chat_role", sa.String(length=10), server_default="branch", nullable=False))
    op.execute("UPDATE messages SET chat_role = 'owner' WHERE target = 'owner'")
    op.add_column("messages", sa.Column("subject_id", sa.Uuid(), nullable=True))
    op.add_column("messages", sa.Column("summary", sa.String(length=200), server_default="", nullable=False))
    op.add_column("messages", sa.Column("document", sa.JSON(), nullable=True))
    op.add_column("messages", sa.Column("reply_markup", sa.JSON(), nullable=True))
    op.add_column("messages", sa.Column("method", sa.String(length=8), server_default="send", nullable=False))
    op.add_column("messages", sa.Column("edit_message_id", sa.String(length=20), nullable=True))
    op.add_column("messages", sa.Column("tg_message_id", sa.String(length=20), nullable=True))
    op.create_index("ix_messages_subject", "messages", ["chat_role", "subject_id", "kind", "created_at"])

    op.create_table(
        "telegram_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.String(length=40), nullable=False),
        sa.Column("tg_user_id", sa.String(length=40), nullable=True),
        sa.Column("label", sa.String(length=80), server_default="", nullable=False),
        sa.Column("via", sa.String(length=12), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlinked_by", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_telegram_links_active", "telegram_links", ["role", "subject_id", "chat_id"], unique=True,
                    postgresql_where=sa.text("unlinked_at IS NULL"))  # fmt: skip
    op.create_index("ix_telegram_links_chat", "telegram_links", ["chat_id"])
    op.create_index("ix_telegram_links_user", "telegram_links", ["tg_user_id"])
    op.create_table(
        "link_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("ref", sa.String(length=80), nullable=False),
        sa.Column("via", sa.String(length=12), nullable=False),
        sa.Column("phone_check", sa.Boolean(), nullable=False),
        sa.Column("label", sa.String(length=80), server_default="", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("uq_link_tokens_ref", "link_tokens", ["role", "ref"], unique=True)
    op.create_table(
        "pending_links",
        sa.Column("chat_id", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_table(
        "customer_consents",
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=24), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("customer_id", "topic"),
    )
    op.create_table(
        "known_customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("preferred_lang", sa.String(length=2), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "known_customer_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("is_clinic", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "branch_prefs",
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("refill_reminder_days", sa.Integer(), nullable=False),
        sa.Column("opening_hours", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("branch_id"),
    )
    op.create_table(
        "telegram_updates",
        sa.Column("update_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("update_id"),
    )
    op.create_table(
        "refill_reminders",
        sa.Column("rx_item_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_version", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("prescription_number", sa.String(length=40), nullable=False),
        sa.Column("medicine_name", sa.String(length=200), nullable=False),
        sa.Column("refills_left", sa.Boolean(), nullable=False),
        sa.Column("dispensed_on", sa.Date(), nullable=False),
        sa.Column("runs_out_on", sa.Date(), nullable=False),
        sa.Column("remind_on", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("rx_item_id"),
    )
    op.create_index("ix_refill_reminders_customer_id", "refill_reminders", ["customer_id"])
    op.create_index("ix_refill_reminders_remind_on", "refill_reminders", ["remind_on"])
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("text_km", sa.String(length=1000), nullable=False),
        sa.Column("text_en", sa.String(length=1000), nullable=False),
        sa.Column("promotion_id", sa.Uuid(), nullable=True),
        sa.Column("queued", sa.Integer(), nullable=False),
        sa.Column("over_cap", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    for table in ("campaigns", "refill_reminders", "telegram_updates", "branch_prefs", "known_customer_groups",
                  "known_customers", "customer_consents", "pending_links", "link_tokens", "telegram_links"):  # fmt: skip
        op.drop_table(table)
    op.drop_index("ix_messages_subject", table_name="messages")
    for col in ("tg_message_id", "edit_message_id", "method", "reply_markup", "document", "summary", "subject_id",
                "chat_role"):  # fmt: skip
        op.drop_column("messages", col)
    op.alter_column("messages", "target", type_=sa.String(length=40))
