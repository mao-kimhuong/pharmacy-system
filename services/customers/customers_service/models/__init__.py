"""SQLAlchemy models of the customers service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.copies import BranchCopyMixin
from pharmacy_shared.numbering import DocSequenceMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .customers import (
    LEDGER_KINDS,
    Customer,
    CustomerAllocation,
    CustomerDebt,
    CustomerGroup,
    CustomerPayment,
    LedgerEntry,
)
from .deposits import Deposit, DepositMovement


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


class DocSequence(DocSequenceMixin, Base):
    __tablename__ = "doc_sequences"


class KnownBranch(BranchCopyMixin, Base):
    """Local copy of branches (branch.* events): codes for payment numbers."""

    __tablename__ = "known_branches"


__all__ = [
    "Deposit",
    "DepositMovement",
    "Base", "Customer", "CustomerAllocation", "CustomerDebt", "CustomerGroup", "CustomerPayment",
    "DocSequence", "KnownBranch", "LEDGER_KINDS", "LedgerEntry", "OutboxEvent", "ProcessedMessage",
]  # fmt: skip
