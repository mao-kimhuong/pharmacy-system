"""Telegram chats, the message outbox (one row per message, never sent twice),
alert settings, and the copies the alert texts need (branches, staff names)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.copies import BranchCopyMixin
from pharmacy_shared.db import IdMixin

from .base import Base


class TelegramChat(Base):
    """target = "owner" or a branch id (the branch's chat)."""

    __tablename__ = "telegram_chats"

    target: Mapped[str] = mapped_column(String(40), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Message(IdMixin, Base):
    """queued → sent | failed | skipped (no bot token / no chat). dedupe_key makes a
    second run of a job (or a replayed event) add nothing.

    T2: chat_role (owner | branch | customer | staff | supplier | reply) decides which
    kinds may go there; customer and supplier rows show only `summary` in the log and
    their text is blanked once sent or failed. `document` = a PDF rendered at send time
    ({type, id, lang}); `method` send | edit (edit_message_id) ; `tg_message_id` = what
    Telegram gave back (approval messages are edited later)."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_due", "status", "next_attempt_at"),
                      Index("ix_messages_subject", "chat_role", "subject_id", "kind", "created_at"))  # fmt: skip

    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    target: Mapped[str] = mapped_column(String(60), index=True)
    branch_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    chat_role: Mapped[str] = mapped_column(String(10), default="branch", server_default="branch")
    subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    summary: Mapped[str] = mapped_column(String(200), default="", server_default="")
    document: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reply_markup: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    method: Mapped[str] = mapped_column(String(8), default="send", server_default="send")
    edit_message_id: Mapped[str | None] = mapped_column(String(20))
    tg_message_id: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertSettings(Base):
    """One row (id 1): thresholds for the money alerts."""

    __tablename__ = "alert_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    large_discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20"))
    large_discount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("10"))
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)


class StockAlert(Base):
    """stock.low / batch.expiring of the night job, sent as one 07:30 digest per branch."""

    __tablename__ = "stock_alerts"

    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    ref: Mapped[str] = mapped_column(String(80), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class KnownBranch(BranchCopyMixin, Base):
    __tablename__ = "known_branches"


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    branch_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
