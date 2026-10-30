"""SQLAlchemy models of the controlled service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.copies import BranchCopyMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .register import (
    ENTRY_TYPES,
    AdjustRequest,
    ControlledProduct,
    Discrepancy,
    KnownStaff,
    RegisterEntry,
    Watermark,
)  # fmt: skip


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


class KnownBranch(BranchCopyMixin, Base):
    __tablename__ = "known_branches"


__all__ = [
    "ENTRY_TYPES", "AdjustRequest", "Base", "ControlledProduct", "Discrepancy", "KnownBranch", "KnownStaff",
    "OutboxEvent", "ProcessedMessage", "RegisterEntry", "Watermark",
]  # fmt: skip
