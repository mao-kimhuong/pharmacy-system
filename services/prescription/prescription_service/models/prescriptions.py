from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base
from .people import Doctor, Patient

RX_STATUSES = ("draft", "active", "partly_dispensed", "fully_dispensed", "expired", "cancelled")
OPEN = ("active", "partly_dispensed")


class Prescription(IdMixin, TimestampMixin, Base):
    """draft → active → partly_dispensed → fully_dispensed; expired (daily job or
    by date); cancelled (reason). Never deleted."""

    __tablename__ = "prescriptions"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'partly_dispensed', 'fully_dispensed', 'expired', 'cancelled')",
            name="ck_prescriptions_status",
        ),
        CheckConstraint("valid_until >= issued_on", name="ck_prescriptions_dates"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id"), index=True)
    rx_no: Mapped[str] = mapped_column(
        String(60), default="", server_default=""
    )  # the number on the paper Rx
    issued_on: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    patient: Mapped[Patient] = relationship(lazy="selectin")
    doctor: Mapped[Doctor] = relationship(lazy="selectin")
    items: Mapped[list["RxItem"]] = relationship(
        back_populates="prescription",
        lazy="selectin",
        order_by="RxItem.line_no",
        cascade="all, delete-orphan",
    )
    attachments: Mapped[list["RxAttachment"]] = relationship(
        lazy="selectin", order_by="RxAttachment.created_at"
    )


class RxItem(IdMixin, Base):
    """One medicine on a prescription. Allowed in total = qty × (1 + repeats);
    remaining = allowed − dispensed − held (held = in a sale not finished yet)."""

    __tablename__ = "rx_items"
    __table_args__ = (
        CheckConstraint("qty_base > 0 AND repeats_allowed >= 0", name="ck_rx_items_qty"),
        CheckConstraint(
            "dispensed_base >= 0 AND held_base >= 0 AND dispensed_base + held_base <= qty_base * (1 + repeats_allowed)",
            name="ck_rx_items_balance",
        ),
    )

    prescription_id: Mapped[UUID] = mapped_column(ForeignKey("prescriptions.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    qty_base: Mapped[int] = mapped_column(Integer)  # one fill, in base units
    dosage: Mapped[str] = mapped_column(String(160), default="", server_default="")
    frequency: Mapped[str] = mapped_column(String(160), default="", server_default="")
    duration_days: Mapped[int | None] = mapped_column(Integer)
    # T2: structured dose for refill reminders (days of supply = qty ÷ (units per dose × doses per day))
    units_per_dose: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    doses_per_day: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    repeats_allowed: Mapped[int] = mapped_column(Integer, default=0)
    dispensed_base: Mapped[int] = mapped_column(Integer, default=0)
    held_base: Mapped[int] = mapped_column(Integer, default=0)

    prescription: Mapped[Prescription] = relationship(back_populates="items")

    @property
    def allowed_base(self) -> int:
        return self.qty_base * (1 + self.repeats_allowed)

    @property
    def remaining_base(self) -> int:
        return self.allowed_base - self.dispensed_base - self.held_base

    @property
    def repeats_used(self) -> int:
        return max(0, -(-self.dispensed_base // self.qty_base) - 1)  # fills started beyond the first


class RxAttachment(IdMixin, Base):
    """A photo or scan of the paper Rx. Stored under a random key in the private
    file store; the original name only here. Downloaded only through the service."""

    __tablename__ = "rx_attachments"

    prescription_id: Mapped[UUID] = mapped_column(ForeignKey("prescriptions.id"), index=True)
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RxHold(IdMixin, Base):
    """The dispensing record: one per invoice line linked to an Rx item.
    held (sale running) → dispensed (invoice.created) / released (sale failed).
    `dispensed_base` follows the invoice: cancel → 0, return → less. Events
    apply absolute targets with the invoice version, so duplicates and
    out-of-order events are harmless."""

    __tablename__ = "rx_holds"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no", name="uq_rx_holds_line"),
        CheckConstraint("status IN ('held', 'dispensed', 'released')", name="ck_rx_holds_status"),
    )

    rx_item_id: Mapped[UUID] = mapped_column(ForeignKey("rx_items.id"), index=True)
    invoice_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    qty_base: Mapped[int] = mapped_column(Integer)  # held / sold
    dispensed_base: Mapped[int] = mapped_column(Integer, default=0)  # what the invoice counts now
    status: Mapped[str] = mapped_column(String(10), default="held")
    version_seen: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    item: Mapped[RxItem] = relationship(lazy="joined")
