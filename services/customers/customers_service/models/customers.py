from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base

LEDGER_KINDS = ("charge", "reversal", "credit_note", "payment", "payment_cancel")


class CustomerGroup(IdMixin, TimestampMixin, Base):
    """Retail, clinic, wholesale... The default discount is stored now and
    applied by sales in S7. Menu hidden by the customer_groups switch."""

    __tablename__ = "customer_groups"
    __table_args__ = (
        Index("uq_customer_groups_name_en", func.lower(text("name_en")), unique=True),
        CheckConstraint(
            "default_discount_pct >= 0 AND default_discount_pct <= 100", name="ck_groups_discount"
        ),
    )

    name_en: Mapped[str] = mapped_column(String(120))
    name_km: Mapped[str] = mapped_column(String(120), default="", server_default="")
    default_discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    # T2: clinics get order status and invoices on Telegram (a flag, not a name to match)
    is_clinic: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    def safe_fields(self) -> dict[str, Any]:
        return {"name_en": self.name_en, "name_km": self.name_km,
                "default_discount_pct": str(self.default_discount_pct), "is_clinic": self.is_clinic,
                "is_active": self.is_active}  # fmt: skip


class Customer(IdMixin, TimestampMixin, Base):
    """Shared by all branches. Never deleted: deactivate. The balance is not
    stored: it is the sum of the ledger."""

    __tablename__ = "customers"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (CheckConstraint("credit_limit >= 0", name="ck_customers_credit_limit"),)

    phone: Mapped[str] = mapped_column(String(20), unique=True)  # normalized: 0XXXXXXXX
    name: Mapped[str] = mapped_column(String(160))
    name_km: Mapped[str] = mapped_column(String(160), default="", server_default="")
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("customer_groups.id"), index=True)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    # T2: language of the customer's Telegram messages; a credit invoice is due this many days after the sale
    preferred_lang: Mapped[str] = mapped_column(String(2), default="km", server_default="km")
    credit_terms_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    group: Mapped[CustomerGroup | None] = relationship(lazy="selectin")

    def safe_fields(self) -> dict[str, Any]:
        return {
            "phone": self.phone, "name": self.name, "name_km": self.name_km,
            "group": self.group.name_en if self.group else None, "credit_limit": str(self.credit_limit),
            "note": self.note, "preferred_lang": self.preferred_lang, "credit_terms_days": self.credit_terms_days,
            "is_active": self.is_active,
        }  # fmt: skip


class LedgerEntry(IdMixin, Base):
    """Every debt and payment, signed in USD (+ the customer owes more, - less).
    Append-only: never edited; a mistake is undone by a reversing entry.
    (ref_type, ref_id) is unique, so a retried charge or reversal is booked once."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("ref_type", "ref_id", name="uq_ledger_ref"),
        CheckConstraint("amount <> 0", name="ck_ledger_amount"),
        CheckConstraint(
            "kind IN ('charge', 'reversal', 'credit_note', 'payment', 'payment_cancel')",
            name="ck_ledger_kind",
        ),
        Index("ix_ledger_customer_seq", "customer_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    branch_id: Mapped[UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    ref_type: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[str] = mapped_column(String(80))
    invoice_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    document_no: Mapped[str] = mapped_column(String(40), default="", server_default="")
    reverses_entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("ledger_entries.id"))
    reason: Mapped[str] = mapped_column(String(255), default="", server_default="")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomerDebt(IdMixin, Base):
    """One unpaid (or partly paid) credit invoice. due = amount - paid - reduced
    (reduced by a cancel or a return's credit note)."""

    __tablename__ = "customer_debts"
    __table_args__ = (
        CheckConstraint("paid >= 0 AND reduced >= 0 AND paid + reduced <= amount", name="ck_debts_amounts"),
        CheckConstraint("status IN ('open', 'paid', 'cancelled')", name="ck_debts_status"),
    )

    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    invoice_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    invoice_no: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    reduced: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(10), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def due(self) -> Decimal:
        return self.amount - self.paid - self.reduced


class CustomerPayment(IdMixin, TimestampMixin, Base):
    __tablename__ = "customer_payments"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_customer_payments_amount"),
        CheckConstraint("method IN ('cash', 'card', 'ABA', 'KHQR')", name="ck_customer_payments_method"),
        CheckConstraint("status IN ('posted', 'cancelled')", name="ck_customer_payments_status"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    method: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reference: Mapped[str] = mapped_column(String(120), default="", server_default="")
    paid_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="posted")
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    allocations: Mapped[list["CustomerAllocation"]] = relationship(back_populates="payment", lazy="selectin")


class CustomerAllocation(IdMixin, Base):
    __tablename__ = "customer_allocations"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_customer_allocations_amount"),)

    payment_id: Mapped[UUID] = mapped_column(ForeignKey("customer_payments.id"), index=True)
    debt_id: Mapped[UUID] = mapped_column(ForeignKey("customer_debts.id"), index=True)
    invoice_no: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)

    payment: Mapped[CustomerPayment] = relationship(back_populates="allocations")
