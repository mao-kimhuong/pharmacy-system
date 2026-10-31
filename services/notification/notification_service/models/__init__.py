"""SQLAlchemy models of the notification service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .telegram import AlertSettings, KnownBranch, Message, Staff, StockAlert, TelegramChat


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


__all__ = ["AlertSettings", "Base", "KnownBranch", "Message", "OutboxEvent", "ProcessedMessage", "Staff",
           "StockAlert", "TelegramChat"]  # fmt: skip
