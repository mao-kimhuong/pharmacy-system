"""Re-ordering (S6): suggestions only, never automatic orders.

- ReorderSetting: per branch + medicine: min, max, supplier lead time, preferred supplier.
- ReorderList / ReorderLine: what the daily job (or a manager) suggests, with the
  numbers behind each line; a manager turns lines into purchase or transfer requests.
- OpenPOLine: open purchase order quantities, from purchase_order.* events.
- AlertSent: stock.low / batch.expiring go out once a day per item.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin

from .base import Base


class ReorderSetting(Base):
    __tablename__ = "reorder_settings"

    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    min_qty: Mapped[int | None] = mapped_column(Integer)  # reorder point; empty = from sales
    max_qty: Mapped[int | None] = mapped_column(Integer)  # order up to; empty = from sales
    lead_time_days: Mapped[int | None] = mapped_column(Integer)  # empty = the branch's default
    preferred_supplier_id: Mapped[UUID | None] = mapped_column(Uuid)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReorderList(IdMixin, Base):
    __tablename__ = "reorder_lists"

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    run_date: Mapped[date] = mapped_column(Date)
    sales_days: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)  # empty = the daily job
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["ReorderLine"]] = relationship(lazy="selectin", order_by="ReorderLine.sku")


class ReorderLine(IdMixin, Base):
    __tablename__ = "reorder_lines"

    list_id: Mapped[UUID] = mapped_column(ForeignKey("reorder_lists.id"), index=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    sku: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(330))
    on_hand: Mapped[int] = mapped_column(Integer)  # sellable: on hand − reserved − quarantined
    in_transit: Mapped[int] = mapped_column(Integer)  # coming by transfer
    on_order: Mapped[int] = mapped_column(Integer)  # open purchase orders
    avg_daily: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    reorder_point: Mapped[int] = mapped_column(Integer)
    target: Mapped[int] = mapped_column(Integer)
    suggested_qty: Mapped[int] = mapped_column(Integer)  # base units, rounded up to the pack
    pack_unit_id: Mapped[UUID | None] = mapped_column(Uuid)
    pack_unit: Mapped[str] = mapped_column(String(40), default="")
    pack_qty: Mapped[int] = mapped_column(Integer, default=0)
    preferred_supplier_id: Mapped[UUID | None] = mapped_column(Uuid)
    last_cost_per_base: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    source_branch_id: Mapped[UUID | None] = mapped_column(Uuid)  # a branch that could send it
    source_reason: Mapped[str] = mapped_column(String(12), default="")  # spare | near_expiry
    source_qty: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="open"
    )  # open | purchase_requested | transfer_requested
    request_number: Mapped[str | None] = mapped_column(String(32))


class OpenPOLine(Base):
    __tablename__ = "open_po_lines"

    po_line_id: Mapped[UUID] = mapped_column(primary_key=True)
    po_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    open_qty: Mapped[int] = mapped_column(Integer)  # ordered − received, 0 when not open
    version: Mapped[int] = mapped_column(Integer)


class AlertSent(Base):
    __tablename__ = "alerts_sent"
    __table_args__ = (UniqueConstraint("kind", "ref", "day", name="uq_alerts_sent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20))
    ref: Mapped[str] = mapped_column(String(80))
    day: Mapped[date] = mapped_column(Date)
