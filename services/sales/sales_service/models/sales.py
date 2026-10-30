from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
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

INVOICE_STATUSES = ("pending", "completed", "failed", "cancelling", "cancelled", "needs_attention")
PAY_METHODS = ("cash", "card", "ABA", "KHQR", "credit")


class ExchangeRate(IdMixin, Base):
    """KHR per USD for one branch. Append-only history: the newest row is the
    rate in use; each row keeps the previous rate (who, when, old -> new)."""

    __tablename__ = "exchange_rates"
    __table_args__ = (CheckConstraint("khr_per_usd BETWEEN 1000 AND 10000", name="ck_exchange_rates_range"),)

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    khr_per_usd: Mapped[int] = mapped_column(Integer)
    previous: Mapped[int | None] = mapped_column(Integer)
    set_by: Mapped[UUID | None] = mapped_column(Uuid)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invoice(IdMixin, TimestampMixin, Base):
    """A sale. pending → completed (numbered) or failed (never numbered: no gaps).
    completed → cancelling → cancelled. needs_attention: a compensation could not
    run; the recovery task retries it. Never deleted.

    Money is USD NUMERIC(14,2); the KHR side keeps the rate used, the KHR total,
    change given in riel and the rounding to 100 riel (so the drawer reconciles)."""

    __tablename__ = "invoices"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("created_by", "idempotency_key", name="uq_invoices_idempotency"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'cancelling', 'cancelled', 'needs_attention')",
            name="ck_invoices_status",
        ),
        CheckConstraint("change_in IN ('USD', 'KHR', 'USD_KHR')", name="ck_invoices_change_in"),
    )

    number: Mapped[str | None] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    patient_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)  # set when lines are dispensed on an Rx
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_by: Mapped[UUID] = mapped_column(Uuid, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    # amounts (USD)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # all payments except credit, in USD
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    change_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))  # change owed
    # KHR side
    khr_per_usd: Mapped[int | None] = mapped_column(Integer)  # the rate this sale used
    total_khr: Mapped[int | None] = mapped_column(Integer)  # total at that rate, rounded to 100 riel
    change_in: Mapped[str] = mapped_column(String(8), default="USD_KHR")
    change_given_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    change_given_khr: Mapped[int] = mapped_column(Integer, default=0)
    # exact change in riel minus what was handed over (+ = the drawer keeps it)
    change_rounding_khr: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    returned_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    # saga
    reservation_id: Mapped[UUID | None] = mapped_column(Uuid)
    failure_code: Mapped[str | None] = mapped_column(String(40))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    cancelled_by: Mapped[UUID | None] = mapped_column(Uuid)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", lazy="selectin", order_by="InvoiceLine.line_no"
    )
    payments: Mapped[list["InvoicePayment"]] = relationship(lazy="selectin", order_by="InvoicePayment.seq")

    @property
    def cost_total(self) -> Decimal:
        return sum((line.cost for line in self.lines), Decimal("0")).quantize(Decimal("0.01"))

    @property
    def margin(self) -> Decimal:
        return self.total - self.cost_total


class InvoiceLine(IdMixin, Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (CheckConstraint("qty > 0 AND qty_base > 0", name="ck_invoice_lines_qty"),)

    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    pack_unit_id: Mapped[UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(330))
    name_km: Mapped[str] = mapped_column(String(160), default="")
    pack_unit: Mapped[str] = mapped_column(String(40))
    qty: Mapped[int] = mapped_column(Integer)  # in the pack unit
    qty_in_base: Mapped[int] = mapped_column(Integer)
    qty_base: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))  # from the batches used
    batch_override_id: Mapped[UUID | None] = mapped_column(Uuid)
    override_reason: Mapped[str | None] = mapped_column(String(255))
    returned_qty_base: Mapped[int] = mapped_column(Integer, default=0)
    # dispensed on a prescription (S4): the Rx, patient and directions as checked at sale time
    rx_item_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    prescription_id: Mapped[UUID | None] = mapped_column(Uuid)
    prescription_number: Mapped[str | None] = mapped_column(String(32))
    patient_id: Mapped[UUID | None] = mapped_column(Uuid)
    patient_name_en: Mapped[str | None] = mapped_column(String(160))
    patient_name_km: Mapped[str | None] = mapped_column(String(160))
    doctor_name: Mapped[str | None] = mapped_column(String(160))
    dosage: Mapped[str | None] = mapped_column(String(160))
    frequency: Mapped[str | None] = mapped_column(String(160))
    duration_days: Mapped[int | None] = mapped_column(Integer)
    # safety warnings shown (en + km) and who accepted them, when
    warnings: Mapped[list | None] = mapped_column(JSON)
    allergy_override_reason: Mapped[str | None] = mapped_column(String(255))
    allergy_override_by: Mapped[UUID | None] = mapped_column(Uuid)
    warnings_acknowledged_by: Mapped[UUID | None] = mapped_column(Uuid)
    warnings_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    invoice: Mapped[Invoice] = relationship(back_populates="lines")
    batches: Mapped[list["InvoiceLineBatch"]] = relationship(lazy="selectin", order_by="InvoiceLineBatch.seq")


class InvoiceLineBatch(IdMixin, Base):
    """Which batches a line was sold from (FEFO split)."""

    __tablename__ = "invoice_line_batches"

    line_id: Mapped[UUID] = mapped_column(ForeignKey("invoice_lines.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    lot_no: Mapped[str] = mapped_column(String(40))
    expiry_date: Mapped[date] = mapped_column(Date)
    qty_base: Mapped[int] = mapped_column(Integer)
    cost_per_base: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    returned_qty_base: Mapped[int] = mapped_column(Integer, default=0)


class InvoicePayment(IdMixin, Base):
    __tablename__ = "invoice_payments"
    __table_args__ = (
        CheckConstraint(
            "method IN ('cash', 'card', 'ABA', 'KHQR', 'credit')", name="ck_invoice_payments_method"
        ),
        CheckConstraint("currency IN ('USD', 'KHR')", name="ck_invoice_payments_currency"),
        CheckConstraint("amount > 0", name="ck_invoice_payments_amount"),
    )

    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))  # in `currency` (riel: whole hundreds)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class SaleReturn(IdMixin, Base):
    """Some lines of an invoice brought back. pending → completed / failed
    (never numbered) / needs_attention (retried by the recovery task)."""

    __tablename__ = "sale_returns"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint("refund_method IN ('cash', 'credit_note')", name="ck_returns_refund"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'needs_attention')", name="ck_returns_status"
        ),
    )

    number: Mapped[str | None] = mapped_column(String(32), unique=True)
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    refund_method: Mapped[str] = mapped_column(String(12))
    refund_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    to_quarantine: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["SaleReturnLine"]] = relationship(lazy="selectin", order_by="SaleReturnLine.seq")


class SaleReturnLine(IdMixin, Base):
    __tablename__ = "sale_return_lines"

    return_id: Mapped[UUID] = mapped_column(ForeignKey("sale_returns.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    invoice_line_id: Mapped[UUID] = mapped_column(ForeignKey("invoice_lines.id"))
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    qty_base: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    opened: Mapped[bool] = mapped_column(Boolean, default=False)
