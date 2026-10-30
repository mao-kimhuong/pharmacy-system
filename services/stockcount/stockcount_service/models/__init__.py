"""SQLAlchemy models of the stockcount service. Import every model here so
Alembic autogenerate can see it."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Numeric
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.copies import BranchCopyMixin
from pharmacy_shared.numbering import DocSequenceMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .counts import COUNT_STATUSES, SCOPES, Count, CountEntry, CountLine


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


class DocSequence(DocSequenceMixin, Base):
    __tablename__ = "doc_sequences"


class KnownBranch(BranchCopyMixin, Base):
    __tablename__ = "known_branches"


class BranchSettingsCopy(Base):
    """branch.settings_updated: when to count twice and when the owner approves."""

    __tablename__ = "branch_settings"

    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    double_count_above_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("50.00"))
    owner_approval_above_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("200.00"))


__all__ = [
    "COUNT_STATUSES", "SCOPES", "Base", "BranchSettingsCopy", "Count", "CountEntry", "CountLine", "DocSequence",
    "KnownBranch", "OutboxEvent", "ProcessedMessage",
]  # fmt: skip
