"""SQLAlchemy models of the prescription service. Import every model here so
Alembic autogenerate can see it."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.copies import BranchCopyMixin, ProductCopyMixin
from pharmacy_shared.numbering import DocSequenceMixin
from pharmacy_shared.outbox import OutboxMixin

from .base import Base
from .people import Doctor, Patient, PatientAllergy, PatientBranch
from .prescriptions import OPEN, RX_STATUSES, Prescription, RxAttachment, RxHold, RxItem


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


class DocSequence(DocSequenceMixin, Base):
    __tablename__ = "doc_sequences"


class KnownBranch(BranchCopyMixin, Base):
    __tablename__ = "known_branches"


class BranchSettingsCopy(Base):
    """branch.settings_updated: how long an Rx is valid by default."""

    __tablename__ = "branch_settings"

    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    rx_valid_days: Mapped[int] = mapped_column(Integer, default=30)


class Product(ProductCopyMixin, Base):
    """medicine.* events, with the ingredients and drug classes for safety checks."""

    __tablename__ = "products"

    active_ingredients: Mapped[list[str]] = mapped_column(JSON, default=list)
    drug_classes: Mapped[list[str]] = mapped_column(JSON, default=list)


class KnownCustomer(Base):
    """customer.* events: a patient may be linked to a customer."""

    __tablename__ = "known_customers"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "Base", "BranchSettingsCopy", "Doctor", "DocSequence", "KnownBranch", "KnownCustomer", "OPEN", "OutboxEvent",
    "Patient", "PatientAllergy", "PatientBranch", "Prescription", "ProcessedMessage", "Product", "RX_STATUSES",
    "RxAttachment", "RxHold", "RxItem",
]  # fmt: skip
