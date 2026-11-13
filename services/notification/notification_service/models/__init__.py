"""SQLAlchemy models of the notification service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .links import (
    DEFAULT_ON,
    ROLES,
    TOPICS,
    Approval,
    BranchPrefs,
    Campaign,
    CustomerConsent,
    KnownCustomer,
    KnownCustomerGroup,
    LinkToken,
    PendingLink,
    RefillReminder,
    TelegramLink,
    TelegramUpdate,
)
from .telegram import AlertSettings, KnownBranch, Message, Staff, StockAlert, TelegramChat


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


__all__ = ["DEFAULT_ON", "ROLES", "TOPICS", "AlertSettings", "Approval", "Base", "BranchPrefs", "Campaign", "CustomerConsent",
           "KnownBranch", "KnownCustomer", "KnownCustomerGroup", "LinkToken", "Message", "OutboxEvent",
           "PendingLink", "ProcessedMessage", "RefillReminder", "Staff", "StockAlert", "TelegramChat",
           "TelegramLink", "TelegramUpdate"]  # fmt: skip
