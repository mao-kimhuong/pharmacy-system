"""Supplier returns (S8b), the supplier credits they create and refunds received."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin

from .base import Base

RETURN_REASONS = ("damaged", "expired", "recalled", "wrong_item", "overstock")


class SupplierReturn(IdMixin, Base):
    """draft → credited (a credit on the supplier's account) | refunded (money back),
    or cancelled (only a draft, with a reason). Stock leaves when it is submitted."""

    __tablename__ = "supplier_returns"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'credited', 'refunded', 'cancelled')", name="ck_supplier_returns_status"),
        CheckConstraint(f"reason IN {RETURN_REASONS}", name="ck_supplier_returns_reason"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    reason: Mapped[str] = mapped_column(String(12))
    note: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[str | None] = mapped_column(String(80), unique=True)  # e.g. recall_line:<id>
    status: Mapped[str] = mapped_column(String(10), default="draft")
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    created_by: Mapped[UUID] = mapped_column(Uuid)
    submitted_by: Mapped[UUID | None] = mapped_column(Uuid)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["SupplierReturnLine"]] = relationship(lazy="selectin", order_by="SupplierReturnLine.line_no",
                                                             cascade="all, delete-orphan")  # fmt: skip


class SupplierReturnLine(IdMixin, Base):
    __tablename__ = "supplier_return_lines"

    return_id: Mapped[UUID] = mapped_column(ForeignKey("supplier_returns.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    qty_base: Mapped[int] = mapped_column(Integer)
    receipt_line_id: Mapped[UUID | None] = mapped_column(Uuid)
    lot_no: Mapped[str] = mapped_column(String(40), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date)
    cost_per_base: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))  # from the batch, when submitted
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))


class SupplierCredit(IdMixin, Base):
    """What the supplier owes us for a return: applied to the branch's open bills,
    oldest first; what is left is applied to the next bills (or refunded)."""

    __tablename__ = "supplier_credits"
    __table_args__ = (CheckConstraint("status IN ('open', 'used', 'refunded')", name="ck_supplier_credits_status"),)

    return_id: Mapped[UUID] = mapped_column(ForeignKey("supplier_returns.id"), unique=True)
    number: Mapped[str] = mapped_column(String(32))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    remaining: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(8), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    allocations: Mapped[list["CreditAllocation"]] = relationship(lazy="selectin")


class CreditAllocation(IdMixin, Base):
    __tablename__ = "supplier_credit_allocations"

    credit_id: Mapped[UUID] = mapped_column(ForeignKey("supplier_credits.id"), index=True)
    receipt_id: Mapped[UUID] = mapped_column(ForeignKey("receipts.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class SupplierRefund(IdMixin, Base):
    """A supplier refund receipt: money the supplier paid back for a return."""

    __tablename__ = "supplier_refunds"

    return_id: Mapped[UUID] = mapped_column(ForeignKey("supplier_returns.id"), unique=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    method: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reference: Mapped[str] = mapped_column(String(120), default="")
    received_on: Mapped[date] = mapped_column(Date)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
