"""Read models of the reports service, built only from other services' events
(services/events.py). Every row is keyed by the source id, so a replayed or
duplicated event changes nothing. Days are Asia/Phnom_Penh calendar days."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.copies import BranchCopyMixin, PackUnitCopyMixin, ProductCopyMixin

from .base import Base

Money = Numeric(14, 2)
Cost = Numeric(14, 4)


# ---------------------------------------------------------------- copies (names for the reports)


class Product(ProductCopyMixin, Base):
    __tablename__ = "products"
    pack_units: Mapped[list["ProductPackUnit"]] = relationship(back_populates="product", lazy="selectin")


class ProductPackUnit(PackUnitCopyMixin, Base):
    __tablename__ = "product_pack_units"
    product: Mapped[Product] = relationship(back_populates="pack_units", lazy="joined")


class KnownBranch(BranchCopyMixin, Base):
    __tablename__ = "known_branches"
    expiry_alert_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [180, 90, 30])


class Lookup(Base):
    """Categories and brands (category.* / brand.*)."""

    __tablename__ = "lookups"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    name_en: Mapped[str] = mapped_column(String(160))
    name_km: Mapped[str] = mapped_column(String(160), default="")


class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(40), default="")


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), default="")
    name: Mapped[str] = mapped_column(String(200))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=0)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    group_id: Mapped[UUID | None] = mapped_column(Uuid)


# ---------------------------------------------------------------- sales


class Invoice(Base):
    """invoice.* (newest version wins). sale_date = completed_at in Phnom Penh;
    a cancelled invoice leaves its day (status cancelled) – choice K."""

    __tablename__ = "invoices"
    __table_args__ = (Index("ix_invoices_branch_day", "branch_id", "sale_date"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    number: Mapped[str | None] = mapped_column(String(32), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    cashier_id: Mapped[UUID | None] = mapped_column(Uuid)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sale_date: Mapped[date | None] = mapped_column(Date)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_date: Mapped[date | None] = mapped_column(Date)
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    subtotal: Mapped[Decimal] = mapped_column(Money)
    discount: Mapped[Decimal] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)
    cost: Mapped[Decimal] = mapped_column(Money)
    khr_per_usd: Mapped[int | None] = mapped_column(Integer)
    total_khr: Mapped[int | None] = mapped_column(BigInteger)
    credit_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    returned_total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))


class InvoiceLine(Base):
    """One sold line (as at sale time). net = after promotion and manual discounts."""

    __tablename__ = "invoice_lines"
    __table_args__ = (
        Index("ix_invoice_lines_branch_day", "branch_id", "sale_date"),
        Index("ix_invoice_lines_medicine_day", "medicine_id", "sale_date"),
        Index("ix_invoice_lines_staff_day", "staff_id", "sale_date"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)  # the sales invoice line id
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    sale_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    staff_id: Mapped[UUID | None] = mapped_column(Uuid)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    category_id: Mapped[UUID | None] = mapped_column(Uuid)
    brand_id: Mapped[UUID | None] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    pack_unit: Mapped[str] = mapped_column(String(40))
    qty: Mapped[int] = mapped_column(Integer)
    qty_base: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    line_total: Mapped[Decimal] = mapped_column(Money)
    promo_discount: Mapped[Decimal] = mapped_column(Money)
    manual_discount: Mapped[Decimal] = mapped_column(Money)
    net: Mapped[Decimal] = mapped_column(Money)
    net_khr: Mapped[int] = mapped_column(BigInteger, default=0)
    cost: Mapped[Decimal] = mapped_column(Money)
    promotion_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_hamper: Mapped[bool] = mapped_column(Boolean, default=False)
    is_rx: Mapped[bool] = mapped_column(Boolean, default=False)
    is_controlled: Mapped[bool] = mapped_column(Boolean, default=False)
    rx_number: Mapped[str | None] = mapped_column(String(40))
    doctor_name: Mapped[str | None] = mapped_column(String(160))
    returned_qty_base: Mapped[int] = mapped_column(Integer, default=0)


class ReturnLine(Base):
    """A returned line, on the day it was returned (choice K)."""

    __tablename__ = "return_lines"
    __table_args__ = (Index("ix_return_lines_branch_day", "branch_id", "return_date"),)

    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # return id : invoice line id : batch
    return_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    number: Mapped[str | None] = mapped_column(String(32))
    invoice_id: Mapped[UUID] = mapped_column(Uuid)
    invoice_number: Mapped[str | None] = mapped_column(String(32))
    line_id: Mapped[UUID] = mapped_column(Uuid)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    return_date: Mapped[date] = mapped_column(Date)
    staff_id: Mapped[UUID | None] = mapped_column(Uuid)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    qty_base: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Money)
    amount_khr: Mapped[int] = mapped_column(BigInteger, default=0)
    cost: Mapped[Decimal] = mapped_column(Money)
    refund_method: Mapped[str] = mapped_column(String(12))
    reason: Mapped[str] = mapped_column(String(255), default="")
    to_quarantine: Mapped[bool] = mapped_column(Boolean, default=False)


class SalesDaily(Base):
    """Rollup per branch, day, medicine and staff of completed sales (rebuilt for
    a branch + day after each invoice event). Feeds the dashboard and summaries."""

    __tablename__ = "sales_daily"

    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    staff_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    qty_base: Mapped[int] = mapped_column(BigInteger)
    gross: Mapped[Decimal] = mapped_column(Money)
    discount: Mapped[Decimal] = mapped_column(Money)
    net: Mapped[Decimal] = mapped_column(Money)
    net_khr: Mapped[int] = mapped_column(BigInteger)
    cost: Mapped[Decimal] = mapped_column(Money)
    lines: Mapped[int] = mapped_column(Integer)


class Payment(Base):
    """All money in (+) and out (−) by method: sale payments and change, refunds,
    invoice cancels, customer payments, deposits, supplier payments."""

    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_branch_day_method", "branch_id", "day", "method"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # kind : source id : n
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    day: Mapped[date] = mapped_column(Date)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(24))
    method: Mapped[str] = mapped_column(String(12))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    amount: Mapped[Decimal] = mapped_column(Money)  # in its currency, signed
    amount_usd: Mapped[Decimal] = mapped_column(Money)  # signed
    reference: Mapped[str] = mapped_column(String(40), default="")
    party: Mapped[str] = mapped_column(String(200), default="")
    staff_id: Mapped[UUID | None] = mapped_column(Uuid)


# ---------------------------------------------------------------- stock


class Movement(Base):
    """stock.changed: every stock movement (signed delta, qty_after per batch)."""

    __tablename__ = "movements"
    __table_args__ = (
        Index("ix_movements_branch_day", "branch_id", "day"),
        Index("ix_movements_batch_seq", "batch_id", "seq"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    type: Mapped[str] = mapped_column(String(20))
    delta: Mapped[int] = mapped_column(Integer)
    qty_after: Mapped[int] = mapped_column(Integer)
    lot_no: Mapped[str] = mapped_column(String(60))
    expiry_date: Mapped[date] = mapped_column(Date)
    cost_per_base: Mapped[Decimal] = mapped_column(Cost)
    reason: Mapped[str] = mapped_column(String(255), default="")
    reason_code: Mapped[str] = mapped_column(String(20), default="")  # shrinkage reason
    ref_type: Mapped[str] = mapped_column(String(40), default="")
    ref_id: Mapped[str] = mapped_column(String(80), default="")
    is_controlled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    day: Mapped[date] = mapped_column(Date)


class StockRow(Base):
    """On hand per branch and batch: the qty_after of the newest movement (by seq)."""

    __tablename__ = "stock"
    __table_args__ = (
        Index("ix_stock_branch_medicine", "branch_id", "medicine_id"),
        Index("ix_stock_expiry_on_hand", "expiry_date", postgresql_where="qty_on_hand > 0"),
    )

    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    lot_no: Mapped[str] = mapped_column(String(60))
    expiry_date: Mapped[date] = mapped_column(Date)
    cost_per_base: Mapped[Decimal] = mapped_column(Cost)
    qty_on_hand: Mapped[int] = mapped_column(Integer)
    last_seq: Mapped[int] = mapped_column(BigInteger)
    last_movement_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Shrinkage(Base):
    """shrinkage.* (pending / posted / rejected)."""

    __tablename__ = "shrinkages"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    lot_no: Mapped[str] = mapped_column(String(60), default="")
    qty_base: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(20))
    value: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20))
    is_controlled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Count(Base):
    """Stock takes (count.*)."""

    __tablename__ = "counts"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(32))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(20), default="")
    variance_value: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CountLine(Base):
    __tablename__ = "count_lines"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    count_id: Mapped[UUID] = mapped_column(ForeignKey("counts.id"), index=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(40))
    lot_no: Mapped[str] = mapped_column(String(60))
    expected_qty: Mapped[int] = mapped_column(Integer)
    counted_qty: Mapped[int] = mapped_column(Integer)
    variance: Mapped[int] = mapped_column(Integer)
    cost_per_base: Mapped[Decimal] = mapped_column(Cost)
    value: Mapped[Decimal] = mapped_column(Money)
    is_controlled: Mapped[bool] = mapped_column(Boolean, default=False)


class Transfer(Base):
    """transfer.* (whole snapshot; newest version wins)."""

    __tablename__ = "transfers"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(String(32))
    from_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    to_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class PendingRequest(Base):
    """Open transfer requests and purchase requests (pending approvals)."""

    __tablename__ = "requests"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # transfer_request | purchase_request
    number: Mapped[str] = mapped_column(String(32))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)  # who must act on it
    status: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    """stock.low / batch.expiring of the daily inventory job."""

    __tablename__ = "alerts"

    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    ref: Mapped[str] = mapped_column(String(80), primary_key=True)  # medicine or batch
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class RegisterIssue(Base):
    """register.discrepancy / chain_broken, open until resolved or cleared."""

    __tablename__ = "register_issues"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    medicine_id: Mapped[UUID | None] = mapped_column(Uuid)
    batch_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    lot_no: Mapped[str] = mapped_column(String(60), default="")
    register_qty: Mapped[int | None] = mapped_column(Integer)
    stock_qty: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- purchasing, customers


class ReceiptLine(Base):
    """goods.received lines (purchases by item / supplier, cost changes)."""

    __tablename__ = "receipt_lines"
    __table_args__ = (Index("ix_receipt_lines_medicine_at", "medicine_id", "received_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    receipt_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    number: Mapped[str] = mapped_column(String(32))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    day: Mapped[date] = mapped_column(Date)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    qty_base: Mapped[int] = mapped_column(Integer)
    lot_no: Mapped[str] = mapped_column(String(60))
    expiry_date: Mapped[date] = mapped_column(Date)
    cost_per_base: Mapped[Decimal] = mapped_column(Cost)
    line_total: Mapped[Decimal] = mapped_column(Money)


class Bill(Base):
    """A receipt is the supplier's bill (payables aging)."""

    __tablename__ = "bills"
    __table_args__ = (Index("ix_bills_due", "due_on"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)  # receipt id
    number: Mapped[str] = mapped_column(String(32))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID] = mapped_column(Uuid)
    received_on: Mapped[date] = mapped_column(Date)
    due_on: Mapped[date] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(Money)


class BillAllocation(Base):
    __tablename__ = "bill_allocations"

    payment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    bill_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)  # 0 once reversed or the payment is cancelled


class Debt(Base):
    """A credit sale's debt (credit.charged), reduced by reversals and payments."""

    __tablename__ = "debts"

    invoice_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    reversed: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    charged_on: Mapped[date] = mapped_column(Date)


class DebtReversal(Base):
    __tablename__ = "debt_reversals"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # invoice : kind : amount : time
    invoice_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)


class DebtAllocation(Base):
    __tablename__ = "debt_allocations"

    payment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(40), primary_key=True, index=True)
    customer_id: Mapped[UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Money)  # 0 once reversed


# ---------------------------------------------------------------- commission, modifications


class CommissionLine(Base):
    __tablename__ = "commission_lines"
    __table_args__ = (Index("ix_commission_lines_branch_month", "branch_id", "month"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    period_id: Mapped[UUID] = mapped_column(Uuid)
    month: Mapped[date] = mapped_column(Date)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    staff_id: Mapped[UUID] = mapped_column(Uuid)
    invoice_number: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(60))
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(40))
    qty_base: Mapped[int] = mapped_column(Integer)
    net_usd: Mapped[Decimal] = mapped_column(Money)
    amount: Mapped[Decimal] = mapped_column(Money)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommissionPeriod(Base):
    __tablename__ = "commission_periods"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    month: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10))


class Modification(Base):
    """Catalog changes from the User Log events (audit.recorded): old → new."""

    __tablename__ = "modifications"
    __table_args__ = (Index("ix_modifications_at", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)  # the event (message) id
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    day: Mapped[date] = mapped_column(Date)
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    branch_id: Mapped[UUID | None] = mapped_column(Uuid)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON)  # [{field, old, new}]


# ---------------------------------------------------------------- backfill


class ReplayCursor(Base):
    """How far the backfill has read each service's outbox (by seq)."""

    __tablename__ = "replay_cursors"

    service: Mapped[str] = mapped_column(String(40), primary_key=True)
    after_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    events: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "Alert", "Bill", "BillAllocation", "CommissionLine", "CommissionPeriod", "Count", "CountLine", "Customer",
    "Debt", "DebtAllocation", "DebtReversal", "Invoice", "InvoiceLine", "KnownBranch", "Lookup", "Modification",
    "Movement", "Payment", "PendingRequest", "Product", "ProductPackUnit", "RegisterIssue", "ReceiptLine",
    "ReplayCursor", "ReturnLine", "SalesDaily", "Shrinkage", "Staff", "StockRow", "Supplier", "Transfer",
]  # fmt: skip
