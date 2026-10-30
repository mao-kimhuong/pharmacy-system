"""Stock transfers between branches (S6).

- TransferRequest: the destination asks a source branch for medicines;
  requested → approved (makes the transfer) | rejected (reason) | cancelled (reason).
- Transfer: approved → picked → dispatched → received → closed, or cancelled
  (reason, only before dispatch). Pushed by the source = starts approved.
- TransferPick: one batch picked for a line (FEFO, or chosen with a reason).
  The batch keeps its identity (lot, expiry, supplier, cost). Picking reserves
  it at the source; dispatch takes it out (in transit); receiving puts the good
  quantity in at the destination.
- TransferDiscrepancy: short, damaged or extra quantity found on receipt,
  resolved by a manager (write-off, return to the source, accept / reject extra).
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin

from .base import Base
from .stock import Batch

REQUEST_STATUSES = ("requested", "approved", "rejected", "cancelled")
TRANSFER_STATUSES = ("approved", "picked", "dispatched", "received", "closed", "cancelled")
DISCREPANCY_KINDS = ("short", "damaged", "extra")
RESOLUTIONS = ("write_off", "return_to_source", "accept", "reject")


class TransferRequest(IdMixin, Base):
    __tablename__ = "transfer_requests"
    __table_args__ = (CheckConstraint(f"status IN {REQUEST_STATUSES}", name="ck_transfer_requests_status"),)

    number: Mapped[str] = mapped_column(String(32), unique=True)
    from_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    to_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(10), default="requested")
    reason: Mapped[str] = mapped_column(String(255), default="")
    needed_by: Mapped[date | None] = mapped_column(Date)
    source_ref: Mapped[str | None] = mapped_column(
        String(80), unique=True
    )  # purchase request / re-order line
    requested_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(255))
    transfer_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["TransferRequestLine"]] = relationship(
        lazy="selectin", order_by="TransferRequestLine.line_no"
    )


class TransferRequestLine(IdMixin, Base):
    __tablename__ = "transfer_request_lines"
    __table_args__ = (CheckConstraint("qty_base > 0", name="ck_transfer_request_lines_qty"),)

    request_id: Mapped[UUID] = mapped_column(ForeignKey("transfer_requests.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    qty_base: Mapped[int] = mapped_column(Integer)
    source_ref: Mapped[str | None] = mapped_column(String(80))  # e.g. purchase request line id


class Transfer(IdMixin, Base):
    __tablename__ = "transfers"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (CheckConstraint(f"status IN {TRANSFER_STATUSES}", name="ck_transfers_status"),)

    number: Mapped[str] = mapped_column(String(32), unique=True)
    from_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    to_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    request_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(12), default="approved")
    note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    picked_by: Mapped[UUID | None] = mapped_column(Uuid)
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_by: Mapped[UUID | None] = mapped_column(Uuid)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_witness: Mapped[str] = mapped_column(String(120), default="")
    received_by: Mapped[UUID | None] = mapped_column(Uuid)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receive_witness: Mapped[str] = mapped_column(String(120), default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["TransferLine"]] = relationship(lazy="selectin", order_by="TransferLine.line_no")
    picks: Mapped[list["TransferPick"]] = relationship(
        lazy="selectin", order_by="(TransferPick.line_no, TransferPick.seq)"
    )
    discrepancies: Mapped[list["TransferDiscrepancy"]] = relationship(lazy="selectin",
                                                                       order_by="TransferDiscrepancy.created_at")  # fmt: skip


class TransferLine(IdMixin, Base):
    __tablename__ = "transfer_lines"
    __table_args__ = (CheckConstraint("qty_base > 0", name="ck_transfer_lines_qty"),)

    transfer_id: Mapped[UUID] = mapped_column(ForeignKey("transfers.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    qty_base: Mapped[int] = mapped_column(Integer)
    is_controlled: Mapped[bool] = mapped_column(default=False)
    source_ref: Mapped[str | None] = mapped_column(String(80))


class TransferPick(IdMixin, Base):
    __tablename__ = "transfer_picks"
    __table_args__ = (CheckConstraint("qty_base > 0", name="ck_transfer_picks_qty"),)

    transfer_id: Mapped[UUID] = mapped_column(ForeignKey("transfers.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"))
    qty_base: Mapped[int] = mapped_column(Integer)
    override_reason: Mapped[str | None] = mapped_column(String(255))
    qty_received: Mapped[int | None] = mapped_column(Integer)  # good, put into stock at the destination
    qty_damaged: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(12), default="")

    batch: Mapped[Batch] = relationship(lazy="joined", innerjoin=True)


class TransferDiscrepancy(IdMixin, Base):
    __tablename__ = "transfer_discrepancies"
    __table_args__ = (
        CheckConstraint(f"kind IN {DISCREPANCY_KINDS}", name="ck_transfer_discrepancies_kind"),
        CheckConstraint("status IN ('open', 'resolved')", name="ck_transfer_discrepancies_status"),
        CheckConstraint("qty_base > 0", name="ck_transfer_discrepancies_qty"),
    )

    transfer_id: Mapped[UUID] = mapped_column(ForeignKey("transfers.id"), index=True)
    pick_id: Mapped[UUID] = mapped_column(ForeignKey("transfer_picks.id"))
    kind: Mapped[str] = mapped_column(String(8))
    qty_base: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8), default="open")
    resolution: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(255), default="")
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shrinkage_id: Mapped[UUID | None] = mapped_column(Uuid)
    movement_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
