from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import Base, IdMixin, TimestampMixin

from .suppliers import Supplier

PAYMENT_METHODS = ("cash", "bank", "ABA", "KHQR")


class SupplierPayment(IdMixin, TimestampMixin, Base):
    """Money paid to a supplier for one branch's receipts, oldest first.
    Never deleted: cancel with a reason (allocations are reversed)."""

    __tablename__ = "supplier_payments"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_supplier_payments_amount"),
        CheckConstraint("method IN ('cash', 'bank', 'ABA', 'KHQR')", name="ck_supplier_payments_method"),
        CheckConstraint("status IN ('posted', 'cancelled')", name="ck_supplier_payments_status"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    method: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reference: Mapped[str] = mapped_column(String(120), default="", server_default="")
    paid_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="posted")
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    supplier: Mapped[Supplier] = relationship(lazy="selectin")
    allocations: Mapped[list["PaymentAllocation"]] = relationship(back_populates="payment", lazy="selectin")


class PaymentAllocation(IdMixin, Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payment_allocations_amount"),)

    payment_id: Mapped[UUID] = mapped_column(ForeignKey("supplier_payments.id"), index=True)
    receipt_id: Mapped[UUID] = mapped_column(ForeignKey("receipts.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)

    payment: Mapped[SupplierPayment] = relationship(back_populates="allocations")
