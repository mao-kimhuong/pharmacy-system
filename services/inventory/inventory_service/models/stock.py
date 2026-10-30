from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin

from .base import Base

BATCH_STATUSES = ("active", "expired", "blocked", "recalled", "quarantine")
MOVEMENT_TYPES = (
    "in", "opening", "out", "sale_cancel", "return", "adjust_in", "adjust_out", "expire_writeoff",
    "transfer_in", "transfer_out", "shrinkage", "count_adjust",
)  # fmt: skip
# Booked once per source (a re-delivered event or a retried call books nothing twice).
ONCE_PER_SOURCE = (
    "in", "opening", "out", "sale_cancel", "return", "shrinkage", "count_adjust", "transfer_in", "transfer_out",
)  # fmt: skip


class Batch(IdMixin, Base):
    """A lot of one medicine: lot number + expiry + supplier + cost per base unit.
    The same lot received again at another cost is a separate batch (FEFO treats
    them alike). Batches are shared by all branches; stock is per branch."""

    __tablename__ = "batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'expired', 'blocked', 'recalled', 'quarantine')", name="ck_batches_status"
        ),
        CheckConstraint("cost_per_base >= 0", name="ck_batches_cost"),
        # One batch per medicine + lot + expiry + supplier + cost (no supplier = same "no supplier").
        Index(
            "uq_batches_identity", "medicine_id", "lot_no", "expiry_date", "supplier_id", "cost_per_base",
            unique=True, postgresql_nulls_not_distinct=True,
        ),
        Index("ix_batches_fefo", "medicine_id", "expiry_date", "received_at"),
    )  # fmt: skip

    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    lot_no: Mapped[str] = mapped_column(String(40))
    expiry_date: Mapped[date] = mapped_column(Date)
    cost_per_base: Mapped[Decimal] = mapped_column(Numeric(14, 4))  # USD
    supplier_id: Mapped[UUID | None] = mapped_column(Uuid)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(12), default="active", server_default="active")
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Stock(IdMixin, Base):
    """Quantity of one batch at one branch, in base units. Changed only by
    services.movements.apply_movement, in the same transaction as the movement."""

    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint("branch_id", "batch_id", name="uq_stock_branch_batch"),
        CheckConstraint("qty_on_hand >= 0", name="ck_stock_on_hand"),
        CheckConstraint("qty_reserved >= 0 AND qty_reserved <= qty_on_hand", name="ck_stock_reserved"),
        CheckConstraint(
            "qty_quarantined >= 0 AND qty_reserved + qty_quarantined <= qty_on_hand",
            name="ck_stock_quarantined",
        ),
    )

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"), index=True)
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    qty_reserved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Returned goods waiting for a pharmacist: counted on hand, never sold.
    qty_quarantined: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    batch: Mapped[Batch] = relationship(lazy="joined", innerjoin=True)


class Movement(IdMixin, Base):
    """Every stock change, signed, in base units. Append-only."""

    __tablename__ = "movements"
    __mapper_args__ = {"eager_defaults": True}  # seq and created_at are read back on insert (stock.changed)
    __table_args__ = (
        CheckConstraint("qty_base <> 0", name="ck_movements_qty"),
        CheckConstraint(
            "type IN ('in', 'opening', 'out', 'sale_cancel', 'return', 'adjust_in', 'adjust_out', "
            "'expire_writeoff', 'transfer_in', 'transfer_out', 'shrinkage', 'count_adjust')",
            name="ck_movements_type",
        ),
        # A receipt line, stock-in line, opening line, sold or returned line is booked
        # once, even if its event or call arrives again.
        Index(
            "uq_movements_source", "type", "ref_type", "ref_id", unique=True,
            postgresql_where=text(
                "type IN ('in', 'opening', 'out', 'sale_cancel', 'return', 'shrinkage', 'count_adjust',"
                " 'transfer_in', 'transfer_out')"
            ),
        ),
        Index("ix_movements_branch_time", "branch_id", "created_at"),
    )  # fmt: skip

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"), index=True)
    medicine_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    type: Mapped[str] = mapped_column(String(20))
    qty_base: Mapped[int] = mapped_column(Integer)  # + in, - out
    qty_after: Mapped[int] = mapped_column(Integer)  # on hand at the branch after this movement
    ref_type: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(255), default="", server_default="")
    # Who/why details for the controlled register: witness, Rx, patient, destruction method...
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    batch: Mapped[Batch] = relationship(lazy="joined", innerjoin=True)


class StockIn(IdMixin, Base):
    """Quick stock-in without a PO (its lines are the movements ref'd to it)."""

    __tablename__ = "stock_ins"

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    supplier_id: Mapped[UUID | None] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OpeningBalance(IdMixin, Base):
    """Initialize: opening stock of one branch, validated line by line before
    it is committed once. Then the branch is locked for initialize."""

    __tablename__ = "opening_balances"
    __table_args__ = (
        CheckConstraint("status IN ('validated', 'has_errors', 'committed')", name="ck_opening_status"),
    )

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(12))
    source: Mapped[str] = mapped_column(String(10))  # api / xlsx
    file_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    total_lines: Mapped[int] = mapped_column(Integer, default=0)
    error_lines: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    committed_by: Mapped[UUID | None] = mapped_column(Uuid)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["OpeningLine"]] = relationship(
        back_populates="opening", lazy="selectin", order_by="OpeningLine.line_no"
    )


class OpeningLine(IdMixin, Base):
    __tablename__ = "opening_lines"

    opening_id: Mapped[UUID] = mapped_column(ForeignKey("opening_balances.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)  # Excel row number for uploads
    data: Mapped[dict] = mapped_column(JSON)  # what was sent, as text
    medicine_id: Mapped[UUID | None] = mapped_column(Uuid)
    pack_unit_id: Mapped[UUID | None] = mapped_column(Uuid)
    lot_no: Mapped[str] = mapped_column(String(40), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date)
    qty: Mapped[int | None] = mapped_column(Integer)
    qty_base: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    cost_per_base: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    short_expiry: Mapped[bool] = mapped_column(default=False)
    errors: Mapped[list[dict]] = mapped_column(JSON, default=list)

    opening: Mapped[OpeningBalance] = relationship(back_populates="lines")


class InitializeLock(Base):
    """After an opening balance is committed the branch is locked for
    initialize; only the owner can unlock it (with a reason)."""

    __tablename__ = "initialize_locks"

    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    locked: Mapped[bool] = mapped_column(default=True)
    opening_id: Mapped[UUID | None] = mapped_column(Uuid)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[UUID | None] = mapped_column(Uuid)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unlocked_by: Mapped[UUID | None] = mapped_column(Uuid)
    unlock_reason: Mapped[str | None] = mapped_column(String(255))


class Reservation(IdMixin, Base):
    """Stock held for a sale while the sale saga runs (one per invoice):
    reserved → confirmed ("out" movements) or released; confirmed → reversed
    (the sale was cancelled: "sale_cancel" movements back to the same batches)."""

    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("ref_type", "ref_id", name="uq_reservations_ref"),
        CheckConstraint(
            "status IN ('reserved', 'confirmed', 'released', 'reversed')", name="ck_reservations_status"
        ),
    )

    ref_type: Mapped[str] = mapped_column(String(20))  # invoice
    ref_id: Mapped[str] = mapped_column(String(80))
    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(10), default="reserved")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lines: Mapped[list["ReservationLine"]] = relationship(
        back_populates="reservation",
        lazy="selectin",
        order_by="(ReservationLine.line_no, ReservationLine.seq)",
    )


class ReservationLine(IdMixin, Base):
    """One batch used for one invoice line (a line split over 2 batches = 2 rows)."""

    __tablename__ = "reservation_lines"
    __table_args__ = (CheckConstraint("qty_base > 0", name="ck_reservation_lines_qty"),)

    reservation_id: Mapped[UUID] = mapped_column(ForeignKey("reservations.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)  # order within the line (FEFO)
    medicine_id: Mapped[UUID] = mapped_column(Uuid)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"))
    qty_base: Mapped[int] = mapped_column(Integer)
    overridden: Mapped[bool] = mapped_column(default=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # controlled sale: Rx, patient, pharmacist

    reservation: Mapped[Reservation] = relationship(back_populates="lines")
    batch: Mapped[Batch] = relationship(lazy="joined", innerjoin=True)


class QuarantineEntry(IdMixin, Base):
    """Quarantine log: returned goods put aside (+) and released by a pharmacist (-)."""

    __tablename__ = "quarantine_entries"

    branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("batches.id"))
    qty_base: Mapped[int] = mapped_column(Integer)
    ref_type: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(255), default="", server_default="")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
