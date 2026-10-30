"""Purchase requests and PO groups (S6).

- PurchaseRequest: a branch asks for medicines; submitted → approved | rejected
  (reason) | cancelled (reason). Approved lines are then ordered (a PO line) or
  filled by a transfer from another branch, and become fulfilled when the goods
  arrive; the requesting branch sees each line's progress.
- POGroup: approved lines of several branches ordered from one supplier at
  once: one PO per branch (S2 POs, receiving and bills unchanged) sharing the
  group number, printed together for the supplier.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base

REQUEST_STATUSES = ("submitted", "approved", "rejected", "cancelled")
LINE_STATUSES = ("submitted", "approved", "rejected", "cancelled", "ordered", "transferring", "fulfilled")


class PurchaseRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "purchase_requests"
    __table_args__ = (CheckConstraint(f"status IN {REQUEST_STATUSES}", name="ck_purchase_requests_status"),)

    number: Mapped[str] = mapped_column(String(32), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(10), default="submitted")
    note: Mapped[str] = mapped_column(String(500), default="")
    source_ref: Mapped[str | None] = mapped_column(String(80), unique=True)  # e.g. a re-order list
    requested_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)

    lines: Mapped[list["PurchaseRequestLine"]] = relationship(
        back_populates="request", lazy="selectin", order_by="PurchaseRequestLine.line_no"
    )


class PurchaseRequestLine(IdMixin, Base):
    __tablename__ = "purchase_request_lines"
    __table_args__ = (
        CheckConstraint(f"status IN {LINE_STATUSES}", name="ck_purchase_request_lines_status"),
        CheckConstraint("qty_base > 0", name="ck_purchase_request_lines_qty"),
    )

    request_id: Mapped[UUID] = mapped_column(ForeignKey("purchase_requests.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    qty_base: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255), default="")
    needed_by: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="submitted")
    po_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    po_number: Mapped[str | None] = mapped_column(String(32))
    po_line_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    transfer_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    transfer_number: Mapped[str | None] = mapped_column(String(32))
    transfer_version: Mapped[int] = mapped_column(Integer, default=0)
    fulfilled_base: Mapped[int] = mapped_column(Integer, default=0)
    source_ref: Mapped[str | None] = mapped_column(String(80))

    request: Mapped[PurchaseRequest] = relationship(back_populates="lines", lazy="joined")


class POGroup(IdMixin, Base):
    __tablename__ = "po_groups"

    number: Mapped[str] = mapped_column(String(32), unique=True)
    supplier_id: Mapped[UUID] = mapped_column(ForeignKey("suppliers.id"))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
