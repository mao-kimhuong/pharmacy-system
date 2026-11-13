"""T2: who a Telegram chat belongs to, one-time link tokens, customer consent,
and the copies the customer messages need.

- TelegramLink: a chat (customer / supplier) or a Telegram user (staff, matched by
  the user id because group chats are shared) linked to one record. Never deleted:
  /stop or unlink sets unlinked_at.
- LinkToken: only the SHA-256 of the token is stored; used once; expires.
- CustomerConsent: one row per customer + topic with when and where it changed.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Index, Integer, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.db import IdMixin

from .base import Base

ROLES = ("customer", "staff", "supplier")
TOPICS = ("receipts", "reminders", "balance", "orders", "show_medicine_names", "marketing")
# On at Start (the customer asked for the bot); medicine names and marketing stay off until chosen
DEFAULT_ON = ("receipts", "reminders", "balance", "orders")


class TelegramLink(IdMixin, Base):
    __tablename__ = "telegram_links"
    __table_args__ = (
        Index("uq_telegram_links_active", "role", "subject_id", "chat_id", unique=True,
              postgresql_where=text("unlinked_at IS NULL")),  # fmt: skip
        Index("ix_telegram_links_chat", "chat_id"),
        Index("ix_telegram_links_user", "tg_user_id"),
    )

    role: Mapped[str] = mapped_column(String(10))
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    chat_id: Mapped[str] = mapped_column(String(40))
    tg_user_id: Mapped[str | None] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80), default="", server_default="")  # supplier contact name
    via: Mapped[str] = mapped_column(String(12))  # receipt | statement | counter | profile | supplier
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unlinked_by: Mapped[str | None] = mapped_column(String(40))  # "customer" (/stop) or a staff user id


class LinkToken(Base):
    __tablename__ = "link_tokens"
    __table_args__ = (Index("uq_link_tokens_ref", "role", "ref", unique=True),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(10))
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    ref: Mapped[str] = mapped_column(String(80))  # invoice:<id>, statement:<customer>:<day>, counter:<n>…
    via: Mapped[str] = mapped_column(String(12))
    phone_check: Mapped[bool] = mapped_column(Boolean, default=True)  # printed tokens: the phone must match
    label: Mapped[str] = mapped_column(String(80), default="", server_default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingLink(Base):
    """A printed token was opened: waiting for the customer to share their phone number."""

    __tablename__ = "pending_links"

    chat_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomerConsent(Base):
    __tablename__ = "customer_consents"

    customer_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    topic: Mapped[str] = mapped_column(String(24), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(16))  # bot_start | bot_settings | bot_stop | staff
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    changed_by: Mapped[UUID | None] = mapped_column(Uuid)


class KnownCustomer(Base):
    """From customer.* events. No name: the messages never greet by name."""

    __tablename__ = "known_customers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), default="")
    preferred_lang: Mapped[str] = mapped_column(String(2), default="km")
    group_id: Mapped[UUID | None] = mapped_column(Uuid)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class KnownCustomerGroup(Base):
    __tablename__ = "known_customer_groups"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    is_clinic: Mapped[bool] = mapped_column(Boolean, default=False)


class BranchPrefs(Base):
    """branch.settings_updated: the settings T2 reads (refill_reminder_days, opening_hours)."""

    __tablename__ = "branch_prefs"

    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    refill_reminder_days: Mapped[int] = mapped_column(Integer, default=3)
    opening_hours: Mapped[dict[str, list[str]] | None] = mapped_column(JSON)


class TelegramUpdate(Base):
    """Each Telegram update is handled once (webhook retries, polling overlap)."""

    __tablename__ = "telegram_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefillReminder(Base):
    """The latest supply of one Rx item (rx.supply). Sent once on remind_on (= runs out − branch days)."""

    __tablename__ = "refill_reminders"

    rx_item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    invoice_id: Mapped[UUID] = mapped_column(Uuid)
    invoice_version: Mapped[int] = mapped_column(Integer, default=0)
    customer_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    prescription_number: Mapped[str] = mapped_column(String(40))
    medicine_name: Mapped[str] = mapped_column(String(200), default="")
    refills_left: Mapped[bool] = mapped_column(Boolean, default=False)
    dispensed_on: Mapped[date] = mapped_column(Date)
    runs_out_on: Mapped[date] = mapped_column(Date)
    remind_on: Mapped[date] = mapped_column(Date, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Campaign(IdMixin, Base):
    """A promotion message to customers who allow marketing (at most 2 a month each)."""

    __tablename__ = "campaigns"

    title: Mapped[str] = mapped_column(String(120))
    text_km: Mapped[str] = mapped_column(String(1000))
    text_en: Mapped[str] = mapped_column(String(1000))
    promotion_id: Mapped[UUID | None] = mapped_column(Uuid)
    queued: Mapped[int] = mapped_column(Integer, default=0)
    over_cap: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
