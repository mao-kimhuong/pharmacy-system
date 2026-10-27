from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import Base, IdMixin, TimestampMixin

from .suppliers import Supplier

PO_STATUSES = ("draft", "sent", "partially_received", "received", "cancelled")


class PurchaseOrder(IdMixin, TimestampMixin, Base):
    """draft → sent → partially_received → received; draft/sent → cancelled
    (only while nothing was received). Never deleted."""

    __tablename__ = "purchase_orders"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'sent', 'partially_received', 'received', 'cancelled')", name="ck_po_status"
        ),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    expected_on: Mapped[date | None] = mapped_column(Date)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    supplier: Mapped[Supplier] = relationship(lazy="selectin")
    lines: Mapped[list["POLine"]] = relationship(
        back_populates="po", lazy="selectin", order_by="POLine.line_no", cascade="all, delete-orphan"
    )

    @property
    def total(self) -> Decimal:
        return sum((line.line_total for line in self.lines), Decimal("0.00"))


class POLine(IdMixin, Base):
    __tablename__ = "po_lines"
    __table_args__ = (
        CheckConstraint("qty > 0 AND qty_base > 0", name="ck_po_lines_qty"),
        CheckConstraint("unit_cost >= 0", name="ck_po_lines_cost"),
        CheckConstraint("qty_received_base >= 0", name="ck_po_lines_received"),
    )

    po_id: Mapped[UUID] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    pack_unit_id: Mapped[UUID] = mapped_column(Uuid)
    qty: Mapped[int] = mapped_column(Integer)  # in pack units
    qty_base: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))  # USD per pack unit
    qty_received_base: Mapped[int] = mapped_column(Integer, default=0)

    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")

    @property
    def qty_in_base(self) -> int:
        return self.qty_base // self.qty

    @property
    def line_total(self) -> Decimal:
        return (self.unit_cost * self.qty).quantize(Decimal("0.01"))


class Receipt(IdMixin, TimestampMixin, Base):
    """Goods received against a PO: the supplier's bill. `paid` grows with
    payment allocations; status is open until fully paid."""

    __tablename__ = "receipts"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint("paid >= 0 AND paid <= total", name="ck_receipts_paid"),
        CheckConstraint("status IN ('open', 'paid')", name="ck_receipts_status"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True)
    po_id: Mapped[UUID] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    supplier_invoice_no: Mapped[str] = mapped_column(String(60), default="", server_default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_on: Mapped[date] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(10), default="open")
    received_by: Mapped[UUID | None] = mapped_column(Uuid)

    po: Mapped[PurchaseOrder] = relationship(lazy="selectin")
    supplier: Mapped[Supplier] = relationship(lazy="selectin")
    lines: Mapped[list["ReceiptLine"]] = relationship(
        back_populates="receipt", lazy="selectin", order_by="ReceiptLine.line_no"
    )

    @property
    def balance(self) -> Decimal:
        return self.total - self.paid


class ReceiptLine(IdMixin, Base):
    __tablename__ = "receipt_lines"
    __table_args__ = (CheckConstraint("qty > 0 AND qty_base > 0", name="ck_receipt_lines_qty"),)

    receipt_id: Mapped[UUID] = mapped_column(ForeignKey("receipts.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    po_line_id: Mapped[UUID] = mapped_column(ForeignKey("po_lines.id"), index=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    pack_unit_id: Mapped[UUID] = mapped_column(Uuid)
    lot_no: Mapped[str] = mapped_column(String(40))
    expiry_date: Mapped[date] = mapped_column(Date)
    qty: Mapped[int] = mapped_column(Integer)  # in pack units
    qty_base: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4))  # per pack unit
    cost_per_base: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    short_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    over_received: Mapped[bool] = mapped_column(Boolean, default=False)
    controlled_schedule: Mapped[str | None] = mapped_column(String(3))

    receipt: Mapped[Receipt] = relationship(back_populates="lines")
